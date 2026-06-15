#!/bin/env python3

import os, sys, time, re, json, glob, fcntl, socket
import argparse
import tarfile
import traceback
import shutil, gzip
import paramiko
import logging
import yaml
import psycopg2
import subprocess, multiprocessing
from types import SimpleNamespace
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from termcolor import colored
from kazoo.client import KazooClient
from kazoo.exceptions import LockTimeout
from logging.handlers import TimedRotatingFileHandler

def getconfig():
  filename = f'{os.getenv("PMS_ONLINE_HOME")}/etc/pmsonline.yml'
  with open(filename, 'r') as ymlfile:
    config = yaml.load(ymlfile, Loader=yaml.FullLoader)
  return config

def timedelta_fromstring(str):
  if str is None:
    return None
  if not re.match(r'^(\d+[dhmsDHMS])(\s+\d+[dhmsDHMS])*$', str):
    raise Exception('Invalid Format: '+str)
  days = 0
  hours = 0
  minutes = 0
  seconds = 0
  tokens = str.lower().split(' ')
  for token in tokens:
    if token.endswith('s'):
      seconds = int(token.replace('s', ''))
    elif token.endswith('m'):
      minutes = int(token.replace('m', ''))
    elif token.endswith('h'):
      hours = int(token.replace('h', ''))
    elif token.endswith('d'):
      days = int(token.replace('d', ''))
  return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)

def timedelta_tostring(dt, m=True, s=False):
  if dt is None:
    return ''
  days, remainder = divmod(abs(dt.total_seconds()), 24*60*60)
  hours, remainder = divmod(remainder, 3600)
  minutes, seconds = divmod(remainder, 60)
  tokens = []
  if int(days) > 0:
    tokens.append('{:d}d'.format(int(days)))
  if int(hours) > 0:
    tokens.append('{:d}h'.format(int(hours)))
  if m and int(minutes) > 0:
    tokens.append('{:d}m'.format(int(minutes)))
  if s and int(seconds) > 0:
    tokens.append('{:d}s'.format(int(seconds)))
  if len(tokens) == 0:
    tokens.append('0s')
  return ' '.join(tokens)

def zkclient():
  zk_settings = getconfig().get('zk', dict())
  zkhost      = zk_settings.get('host')
  zktimeout   = zk_settings.get('timeout', 10)
  zk = KazooClient(hosts=zkhost, timeout=zktimeout)
  zk.start()
  return zk

def connect_ssh(hostname, port, user, passwd=None):
  logging.info('Connecting to {}@{}'.format(user, hostname))
  ssh = paramiko.SSHClient()
  ssh.load_system_host_keys()
  ssh.set_missing_host_key_policy(paramiko.client.AutoAddPolicy())
  ssh.connect(hostname, port=port, username=user, password=passwd, timeout=30, auth_timeout=30)
  logging.info('Connected {}@{}'.format(user, hostname))
  return ssh

def remote_exec(ssh, command, timeout=None):
  logging.info('ssh.exec {}'.format(command))
  outlines = []
  # set timeout = None (no timeout)
  # since there're some command i.e. tar that take long time to complete
  # otherwise, paramiko will return with incomplete data
  stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout, get_pty=True)
  lines = stdout.readlines()
  for line in lines:
    outlines.append(line.strip())
  return outlines

def delete_files(infile_pattern, retention):
  if retention is not None:
    for infile in glob.glob(infile_pattern):
      stat = os.stat(infile)
      mtime = datetime.fromtimestamp(stat.st_mtime)
      if (datetime.now() - mtime) > retention:
        os.unlink(infile)
        logging.info(f'{infile} [deleted]')

def pg_dsn():
  dbconf  = getconfig().get('database', dict())
  host    = dbconf.get('host')
  port    = dbconf.get('port', 5432)
  dbname  = dbconf.get('database')
  user    = dbconf.get('user')
  passwd  = dbconf.get('password')
  return f"host={host} port={port} dbname={dbname} user={user} password={passwd}"

def pg_connect():
  dbconf  = getconfig().get('database', dict())
  host    = dbconf.get('host')
  port    = dbconf.get('port', 5432)
  dbname  = dbconf.get('database')
  user    = dbconf.get('user')
  passwd  = dbconf.get('password')
  db = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=passwd)
  db.autocommit = False
  return db

def pg_reset_part(tbname, dt, part_range=1):
  # part_range = number of days for each partition (default = 1)
  # drop and re-create partition
  # dt = '2022-12-01'
  try:
    logging.info(f'pg_reset_part: {tbname}, dt={dt}, part_range={part_range}')
    db = pg_connect()
    cs = db.cursor()
    pdate     = datetime.strptime(dt, '%Y-%m-%d')
    partname  = datetime.strftime(pdate, 'p%Y%m%d00')
    parttable   = f'{tbname}_{partname}'

    # DROP TABLE IF EXISTS traffic1d_p2022120900
    sql = f'DROP TABLE IF EXISTS {parttable}'
    logging.info(f'SQL> {sql}')
    cs.execute(sql)

    # CREATE TABLE IF NOT EXISTS traffic1d_p2022120900 PARTITION OF traffic1d FOR VALUES FROM ('2022-12-09') TO ('2022-12-10')
    dt_start = datetime.strftime(pdate + timedelta(days=0), '%Y-%m-%d')
    dt_end   = datetime.strftime(pdate + timedelta(days=part_range), '%Y-%m-%d')
    sql = f"CREATE TABLE IF NOT EXISTS {parttable} PARTITION OF {tbname} FOR VALUES FROM ('{dt_start}') TO ('{dt_end}')"
    logging.info(f'SQL> {sql}')
    cs.execute(sql)
    cs.close()
    db.commit()
    db.close()
  except Exception as ex:
    logging.error(f'Error: {str(ex)}')
    
def save_auditlog(app, name, start, dt, cnt, errmsg):
  try:
    db = pg_connect()
    cs = db.cursor()
    if errmsg is not None:
      errmsg = errmsg[:255]
    cs.execute("""
                insert into job(id, app, name, host, start, completed, dt, cnt, errmsg)
                values(nextval('job_seq'), %s, %s, %s, %s, %s, %s, %s, %s)
               """, (app, name, socket.gethostname(), start, datetime.now(), dt, cnt, errmsg))
    cs.close()
    db.commit()
    db.close()
  except Exception as ex:
    raise ex

def gzipfile(infile):
  # create gzip file and delete original file
  parentdir = os.path.dirname(infile)
  filename  = os.path.basename(infile)
  gzfile    = os.path.join(parentdir, filename+'.gz')
  with open(infile, 'rb') as fin:
    with gzip.open(gzfile, 'wb') as fout:
      shutil.copyfileobj(fin, fout)
  os.unlink(infile)

def gunzipfile(gzfile):
  # extract gzip file and delete original file
  parentdir = os.path.dirname(gzfile)
  filename  = os.path.basename(gzfile).replace('.gz', '')
  outfile   = os.path.join(parentdir, filename)
  with gzip.open(gzfile, 'rb') as fin:
    with open(outfile, 'wb') as fout:
      shutil.copyfileobj(fin, fout)
  os.unlink(gzfile)
  return outfile
          
def mklock(lockfile):
  lock = open(lockfile, 'w+')
  fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
  return lock

def rmlock(lockfile):
  if lockfile:
    filename = lockfile.name
    fcntl.flock(lockfile, fcntl.LOCK_UN)
    Path(filename).unlink()
    
def getlastxfer(xferfile):
  try:
    if not os.path.exists(xferfile):
      return None
    with open(xferfile, 'r') as fin:
      line = fin.read().strip()
      return datetime.strptime(line, '%Y%m%dT%H%M%S')
  except Exception as ex:
    return None
  
def savelastxfer(xferfile, dt):
  parentdir = Path(xferfile).parent
  if not os.path.exists(parentdir):
    os.makedirs(parentdir, exist_ok=True)
  if dt is None:
    dt = datetime.now()  
  dtstr = datetime.strftime(dt, '%Y%m%dT%H%M%S')
  with open(xferfile, 'w') as fout:  
    fout.write(f'{dtstr}')

def sftp_listfiles(host, user, password, sftpdir, filePattern):
  # return list of {filepath: <filepath>, mtime: datetime}
  # sort by mtime asc
  remotefiles = []
  ssh = connect_ssh(host, 22, user, password)
  sftp = ssh.open_sftp()
  for file in sftp.listdir(sftpdir):
    m = re.match(filePattern, file)
    if m:
      filename    = os.path.basename(file)
      remotefile  = os.path.join(sftpdir, file)
      attr        = sftp.stat(remotefile)
      mtime       = datetime.fromtimestamp(attr.st_mtime)
      logging.info(f'{remotefile}|{mtime}')
      # logging.info(f'sftp_listfiles: {remotefile}')
      remotefiles.append(SimpleNamespace(filepath=remotefile, mtime=mtime))
  
  sftp.close()
  ssh.close()
  
  # Sort by mtime ascending
  sorted_files = sorted(remotefiles, key=lambda x: x.mtime, reverse=False)
  return sorted_files

def sftp_getfiles(host, user, password, remotefiles, localdir):
  ssh = connect_ssh(host, 22, user, password)
  sftp = ssh.open_sftp()
  
  os.makedirs(localdir, exist_ok=True)
  for remotefile in remotefiles:
    filename    = os.path.basename(remotefile)
    localfile   = os.path.join(localdir, filename)
    
    logging.info(f'sftp_getfiles: {remotefile} to {localfile}')
    # sftp.get(remotefile, localfile)
    sftp.MAX_PACKET_SIZE = 32768
    with open(localfile, 'wb') as fout:
      sftp.getfo(remotefile, fout)
      
  sftp.close()
  ssh.close()
