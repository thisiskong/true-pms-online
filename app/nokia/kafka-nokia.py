#!/bin/env python3

import os, sys, socket, time
import json, yaml
import argparse
import logging, traceback
import threading
import queue
import pmslib
from types import SimpleNamespace
from datetime import datetime, timedelta
from pathlib import Path
from confluent_kafka import Consumer, TopicPartition
from confluent_kafka.admin import AdminClient
from logging.handlers import TimedRotatingFileHandler

datadir   = f'{os.getenv("PMS_ONLINE_HOME")}/data/nokia'
REPORT_INTERVAL = 5
  
def create_file_writer():
  logger = logging.getLogger("nokia_data")
  logger.setLevel(logging.INFO)
  logger.propagate = False

  hostname = socket.gethostname()
  logdir   = f'{os.getenv("PMS_ONLINE_HOME")}/data/nokia'
  os.makedirs(logdir, exist_ok=True)

  handler = TimedRotatingFileHandler(
    filename    = os.path.join(logdir, f"nokia-{hostname}.current"),
    when        = "M",
    interval    = 5,
    backupCount = 10,
    encoding    = "utf-8",
    utc         = False,
  )

  def namer(default_name):
    timestamp_str = default_name.split(".")[-1]
    dt = datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M")
    return os.path.join(logdir, f"nokia-{hostname}-{dt.strftime('%Y%m%dT%H%M')}.json")

  handler.namer = namer
  handler.setFormatter(logging.Formatter("%(message)s"))

  if not logger.handlers:
    logger.addHandler(handler)

  return logger

def kafka_getconfig():
  ssl_config          = pmslib.getconfig().get('fttx', dict()).get('kafka_nokia', dict()).get('ssl_config', dict())
  group_id            = ssl_config.get('group_id')
  bootstrap_servers   = ssl_config.get('bootstrap_servers')
  ssl_certfile        = ssl_config.get('ssl_certfile')    # av-kafka-client-cert.pem
  ssl_keyfile         = ssl_config.get('ssl_keyfile')     # av-kafka-client-key.pem
  ssl_cafile          = ssl_config.get('ssl_cafile')      # av-kafka-client-trustchain-cert.pem
  ssl_keypass         = ssl_config.get('ssl_keypass')     # zgFBycnQkjZ@EPQq
  kafka_config = {
    'group.id': group_id,
    'auto.offset.reset': 'earliest',
    'enable.auto.commit': True,
    'bootstrap.servers': bootstrap_servers,
    'security.protocol': 'SSL',
    'ssl.endpoint.identification.algorithm': 'none',
    'ssl.ca.location':          ssl_cafile,
    'ssl.certificate.location': ssl_certfile,
    'ssl.key.location':         ssl_keyfile,
    'ssl.key.password':         ssl_keypass,
    # 'connections.max.idle.ms': 5000,
    # 'request.timeout.ms': 5000,
    # 'socket.timeout.ms': 5000,
    # 'socket.connection.setup.timeout.ms': 5000,
    # 'retries': 1,
    # 'retry.backoff.ms': 500,
  }
  return kafka_config

def kafka_gettopic():
  return pmslib.getconfig().get('fttx', dict()).get('kafka_nokia', dict()).get('kafka_topic')

def kafka_list_topics():
  kafa_config = kafka_getconfig()
  admin = AdminClient(kafa_config)
  md = admin.list_topics(timeout=10)
  topics = list(md.topics.keys())
  for t in topics:
    print(t)
  return topics
    
def on_assign(consumer, partitions):
  logging.info(f'ASSIGNED: {partitions}')

def on_revoke(consumer, partitions):
  print(f'REVOKED: {partitions}')
  
def coalesce(data, names):
  # return first non-null value
  return next((data.get(k) for k in names if data.get(k) is not None), None)

def to_float(value):
  try:
    return float(value)
  except (TypeError, ValueError):
    return None
  
def worker(file_writer, queue):
  while True:
    msg = queue.get()
    try:
      handle_message(file_writer, msg)
    except Exception as ex:
      logging.exception(f'Error: worker error: {str(ex)}', exc_info=True)
    finally:
      queue.task_done()

def compute_delta(rockdb, serial, name, value):
  if value is None:
    return None
  
  value = int(value)
  key = f'{serial}|{name}'.encode()
  prev_bytes = rockdb.get(key)
  if prev_bytes is not None:
    prev = int(prev_bytes)
    delta = value - prev
    
    # counter reset protection
    if delta < 0:
      delta = value
  else:
    delta = None
    
  rockdb.put(key, str(value).encode())
  return delta
    
def handle_message(file_writer, msg):
  try:
    data = json.loads(msg.value().decode('utf-8'))
    # logging.info(json.dumps(data, indent=2))

    # # print(json.dumps(rec))
    file_writer.info(json.dumps(data))
    
  except Exception as ex:
    logging.error(f'Error: {str(ex)}', exc_info=True)

def kafka_consumer_event(partition_list):
  try:
    rockdbdir = f'{datadir}/counter.db'
    queue_    = queue.Queue(maxsize=10000)  # prevent unlimited memory growth
    lock_     = threading.Lock()
    db_       = rocksdb.DB(rockdbdir, rocksdb.Options(create_if_missing=True))

    client_id     = f'{socket.gethostname()}-{os.getcwd()}'
    kafka_config  = kafka_getconfig().copy()
    kafka_topic   = kafka_gettopic()
    kafka_config['client.id'] = client_id
        
    logging.info(f'kafka_config={kafka_config}')
    logging.info(f'kafka_topic={kafka_topic}')
    # logging.info(f'kafka_debug_serials={debug_serials}')
    
    consumer = Consumer(kafka_config)
    
    if partition_list and len(partition_list) > 0:
      # partition pinning
      partitions = []
      for p in partition_list:
        partitions.append(TopicPartition(kafka_topic, p))
      consumer.assign(partitions)
      logging.info(f'Subscribed to topic: {kafka_topic} for partitions: {partition_list}')
    else:
      consumer.subscribe([kafka_topic], on_assign=on_assign, on_revoke=on_revoke)
      logging.info(f'Subscribed to topic: {kafka_topic}')
    
    # create file writer
    file_writer = create_file_writer()
    
    # start workers
    for _ in range(2):
      threading.Thread(target=worker, args=(file_writer, queue_), daemon=True).start()
    
    msg_count = 0
    interval_count = 0
    last_report = time.time()
    
    while True:
      msg = consumer.poll(0)
      if msg is None:
        continue
      if msg.error():
        logging.error(f'Error: {msg.error()}')
        continue
      if msg.value() is None:
        logging.error(f'Error: msg is None')
        continue
      
      # process message
      msg_count += 1
      interval_count += 1

      now = time.time()

      if now - last_report >= REPORT_INTERVAL:

        rate = interval_count / (now - last_report)

        total_lag = 0
        partitions = consumer.assignment()
        partition_list = []

        for p in partitions:
          partition_list.append(p.partition)

          low, high = consumer.get_watermark_offsets(p, cached=True)
          pos = consumer.position([p])[0].offset
          lag = high - pos
          total_lag += lag
          # logging.info(f'partition={p.partition} lag={lag}')
          
        logging.info(f'{client_id} | partitions={partition_list} | rate={rate:,.0f}/s | lag={total_lag:,}')
        
        interval_count = 0
        last_report = now
    
      try:
        queue_.put(msg, timeout=1)
      except queue.Full:
        logging.warning(f'Error: message queue full, dropping message')

  except KeyboardInterrupt:
    logging.info('Stopping consumer...')
  finally:
    consumer.close()
    
def decodefile(infile):
  with open(infile, 'r') as fin:
    for line in fin:
      line = line.strip()
      if not line:
        continue
      data = json.loads(line)
      decode_event(data)
      # print(json.dumps(data, indent=2))

def decode_event(data):
  records = data.get('anv:device-manager', dict()).get('anv-device-holders:device', [])
  for rec in records:
    device_id   = rec.get('device-id')
    ts          = rec.get('timestamp')
    tstamp      = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z") + timedelta(hours=7)
    device_data = rec.get('device-specific-data')
    for key1, val1 in device_data.items():
      for key2, val2 in val1.items():
        # print(f'{key1}|{key2}')
        # bbf-fiber-onu-emulated-mount:onus|onu
        if key1 == 'bbf-fiber-onu-emulated-mount:onus' and key2 == 'onu':
          print(f'{key1}|{key2}')
          decode_onu(val2)
          print(json.dumps(val2, indent=2))
        # bbf-fiber-onu-emulated-mount:onus|onu
        # ietf-hardware:hardware-state|component
        # ietf-interfaces:interfaces-state|interface
        # nokia-conf:configure|port
        # nokia-state:state|port
    # ports     = data.get('port', [])
    # print(f'{device_id}|{tstamp}|{ports}')

def decode_onu(onu_data):
  for rec in onu_data:
    name  = rec.get('name')
    intfs = rec.get('root', dict()).get('ietf-hardware-mounted:hardware-state', dict()).get('component', [])
    for intf in intfs:
      name = intf.get('name')
      type = intf.get('type')
      admin_status = intf.get('admin-status')
      oper_status  = intf.get('oper-status')
      lastchange   = intf.get('last-change')
      print(f'{name}|{type}|{admin_status}|{oper_status}|{lastchange}')

def decode_file(infile):
  with open(infile, 'r') as fin:
    for line in fin:
      rec = json.dump(line.strip())
      
#-----------------------------------
# Main
#-----------------------------------
def main(args):
  lock = None
  try:
    parser = argparse.ArgumentParser(description='Nokia Kafka Consumer')
    parser.add_argument('--list', action='store_true', help='List Kafka topic')
    parser.add_argument('--consumer', action='store_true', help='Consume event from topic')
    parser.add_argument('--partition', nargs='+', default=[], metavar='partition', help='Partition pinning')
    parser.add_argument('--decode', nargs='?', metavar=('jsonfile'), help='Decode file')
    parser.add_argument('--debug', action='store_true', help='Logging debug level')
    args = parser.parse_args()
    
    # logging
    loglv = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(stream=sys.stdout, level=loglv, format='%(asctime)s %(levelname)8s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    homepath = os.getenv('PMS_ONLINE_HOME')
    logfile = os.path.join(homepath, 'logs', f'kafka-nokia.log')
    handler = TimedRotatingFileHandler(logfile, when='midnight', backupCount=15)
    handler.setFormatter(logging.Formatter(fmt='%(asctime)s %(levelname)8s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logging.getLogger().addHandler(handler)
    logging.getLogger("kafka").setLevel(logging.CRITICAL)
    
    if args.list:
      kafka_list_topics()
      
    elif args.consumer:
      # do not allow multiple instance on same host
      lock = pmslib.mklock('/tmp/nokia.lck')
      kafka_consumer_event(args.partition)
    
    elif args.decode:
      jsonfile = args.decode
      decodefile(jsonfile)

    else:
      print('')
      parser.print_help()
      print('')

  except BlockingIOError as ex:
    print('Error! Another process is running.')
    sys.exit(2)

  except Exception as ex:
    logging.error(str(ex), exc_info=True)
    sys.exit(2)
  
  finally:
    pmslib.rmlock(lock)

if __name__ == "__main__":
  main(sys.argv[1:])
  sys.exit()
  
