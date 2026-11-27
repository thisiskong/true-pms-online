DataSource:
- daily metric for each ONU
       select device, ponport, ontid, vendor, model, moduleclass, l1name, l2name, ranging,
              onu_rxpwr, onu_txpwr, onu_current, onu_voltage, onu_temp,
              onu_in_biperr, onu_out_biperr,
              radius_porterror, radius_adminreset, radius_nasrequest, radius_idletimeout, radius_lostcarrier, radius_sesstimeout, radius_userrequest
       from onu_pon_1d
       where tstamp >= now() - interval '3 days'

- passive device inventory
       select device, ponport, ontid, l1name, l2name, l1len, l2len, l1ratio, l2ratio, splitratio
       from odn_onu


create a python script to export data from postgres using above query and save to jsonl file.

