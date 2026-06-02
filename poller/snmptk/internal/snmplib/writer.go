package snmplib

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/xitongsys/parquet-go-source/local"
	"github.com/xitongsys/parquet-go/parquet"
	"github.com/xitongsys/parquet-go/source"
	"github.com/xitongsys/parquet-go/writer"
)

type DatalakeRecord struct {
	CollectTime         string   `json:"collectTime,omitempty"`
	Ip                  string   `json:"ip,omitempty"`
	Ifindex             string   `json:"ifindex,omitempty"`
	Device              string   `json:"device,omitempty"`
	Name                string   `json:"name,omitempty"`
	Ifname              string   `json:"ifname,omitempty"`
	Ifalias             string   `json:"ifalias,omitempty"`
	Ifdescr             string   `json:"ifdescr,omitempty"`
	Iftype              string   `json:"iftype,omitempty"`
	Ifspeed             int64    `json:"ifspeed,omitempty"`
	Dstname             string   `json:"dstname,omitempty"`
	Dstport             string   `json:"dstport,omitempty"`
	Dstsite             string   `json:"dstsite,omitempty"`
	Dsttype             string   `json:"dsttype,omitempty"`
	Network             string   `json:"network,omitempty"`
	Topology            string   `json:"topology,omitempty"`
	Meas                int64    `json:"meas,omitempty"`
	In_rate_gpbs        *float64 `json:"in_rate_gbps,omitempty"`
	Out_rate_gbps       *float64 `json:"out_rate_gbps,omitempty"`
	In_mean_bw_percent  *float64 `json:"in_mean_bw_percent,omitempty"`
	Out_mean_bw_percent *float64 `json:"out_mean_bw_percent,omitempty"`
	In_crcerr           *int64   `json:"in_crcerr,omitempty"`
	In_crcerr_acc       *int64   `json:"in_crcerr_acc,omitempty"`
}

type JsonRecord struct {
	CollectTime              JsonTime     `json:"collectTime,omitempty"`
	Ip                       string       `json:"ip,omitempty"`
	Ifindex                  string       `json:"ifindex,omitempty"`
	Meas                     int64        `json:"meas,omitempty"`
	Ifspeed                  int64        `json:"ifspeed,omitempty"`
	Ifoper                   string       `json:"ifoper,omitempty"`
	In_octets1               *uint64      `json:"in_octets1,omitempty"`
	In_octets2               *uint64      `json:"in_octets2,omitempty"`
	In_octets                *uint64      `json:"in_octets,omitempty"`
	In_flg                   string       `json:"in_flg,omitempty"`
	Out_octets1              *uint64      `json:"out_octets1,omitempty"`
	Out_octets2              *uint64      `json:"out_octets2,omitempty"`
	Out_octets               *uint64      `json:"out_octets,omitempty"`
	Out_flg                  string       `json:"out_flg,omitempty"`
	In_rate                  *int64       `json:"in_rate,omitempty"`
	Out_rate                 *int64       `json:"out_rate,omitempty"`
	In_bw                    *float64     `json:"in_bw,omitempty"`
	Out_bw                   *float64     `json:"out_bw,omitempty"`
	In_err1                  *interface{} `json:"in_err1,omitempty"`
	In_err2                  *interface{} `json:"in_err2,omitempty"`
	In_err                   *interface{} `json:"in_err,omitempty"`
	in_octets_tsdb_overflow  bool
	out_octets_tsdb_overflow bool
}

type OfflineRecord struct {
	CollectTime JsonTime `json:"collectTime,omitempty"`
	Ip          string   `json:"ip,omitempty"`
	Device      string   `json:"device,omitempty"`
	Sitename    string   `json:"sitename,omitempty"`
}

type ParquetRecord struct {
	Collecttime int64   `parquet:"name=Collecttime, type=INT64, convertedtype=TIMESTAMP_MILLIS"`
	Ip          string  `parquet:"name=Ip, type=BYTE_ARRAY, convertedtype=UTF8, encoding=PLAIN_DICTIONARY"`
	Ifindex     string  `parquet:"name=Ifindex, type=BYTE_ARRAY, convertedtype=UTF8, encoding=PLAIN_DICTIONARY"`
	Meas        int64   `parquet:"name=Meas, type=INT64"`
	Ifspeed     int64   `parquet:"name=Ifspeed, type=INT64"`
	Ifoper      string  `parquet:"name=Ifoper, type=BYTE_ARRAY, convertedtype=UTF8, encoding=PLAIN_DICTIONARY"`
	Ifdiscon    uint64  `parquet:"name=Ifdiscon, type=INT64"`
	In_octets1  string  `parquet:"name=In_octets1, type=FIXED_LEN_BYTE_ARRAY, convertedtype=DECIMAL, scale=0, precision=3, length=3"`
	In_octets2  int64   `parquet:"name=In_octets2, type=INT64"`
	In_octets   int64   `parquet:"name=In_octets, type=INT64"`
	In_flg      string  `parquet:"name=In_flg, type=BYTE_ARRAY, convertedtype=UTF8, encoding=PLAIN_DICTIONARY"`
	Out_octets1 int64   `parquet:"name=Out_octets1, type=INT64"`
	Out_octets2 int64   `parquet:"name=Out_octets2, type=INT64"`
	Out_octets  int64   `parquet:"name=Out_octets, type=INT64"`
	Out_flg     string  `parquet:"name=Out_flg, type=BYTE_ARRAY, convertedtype=UTF8, encoding=PLAIN_DICTIONARY"`
	In_rate     float32 `parquet:"name=In_rate, type=FLOAT"`
	Out_rate    float32 `parquet:"name=Out_rate, type=FLOAT"`
	In_bw       float32 `parquet:"name=In_bw, type=FLOAT"`
	Out_bw      float32 `parquet:"name=Out_bw, type=FLOAT"`
	In_err1     int64   `parquet:"name=In_err1, type=INT64"`
	In_err2     int64   `parquet:"name=In_err2, type=INT64"`
	In_err      int64   `parquet:"name=In_err, type=INT64"`
}

func WriteParquet(outfile string) error {
	var err error
	fw, err := local.NewLocalFileWriter(outfile)
	if err != nil {
		log.Printf("Error! Can't create file: %v", err)
		return err
	}
	//write
	pw, err := writer.NewParquetWriter(fw, new(ParquetRecord), 4)
	if err != nil {
		log.Printf("Error! Can't create parquet writer: %v", err)
		return err
	}

	pw.RowGroupSize = 128 * 1024 * 1024 //128M
	pw.PageSize = 8 * 1024              //8K
	pw.CompressionType = parquet.CompressionCodec_SNAPPY
	num := 100
	for i := 0; i < num; i++ {
		record := ParquetRecord{
			Collecttime: int64(time.Now().UnixNano() / 1000000),
			Ip:          "10.1.2.3",
			Ifindex:     "1",
			Meas:        300,
			Ifspeed:     1000000,
			Ifoper:      "up",
			Ifdiscon:    0,
			In_octets1:  "100",
			In_octets2:  200,
			In_octets:   100,
			In_flg:      "normal",
			Out_octets1: 100,
			Out_octets2: 200,
			Out_octets:  100,
			Out_flg:     "normal",
			In_rate:     float32(1.1),
			Out_rate:    float32(1.2),
			In_bw:       float32(2.1),
			Out_bw:      float32(2.2),
			In_err1:     int64(3),
			In_err2:     int64(4),
			In_err:      int64(3),
		}
		if err = pw.Write(record); err != nil {
			log.Printf("Error! Write record: %v", err)
		}
	}
	if err = pw.WriteStop(); err != nil {
		log.Printf("Error! %v", err)
		return err
	}

	fw.Close()
	return nil
}

func NewParquetWriter(outfile string) (source.ParquetFile, *writer.ParquetWriter, error) {
	var err error
	fw, err := local.NewLocalFileWriter(outfile)
	if err != nil {
		return nil, nil, err
	}
	//write
	pw, err := writer.NewParquetWriter(fw, new(ParquetRecord), 4)
	if err != nil {
		return nil, nil, err
	}

	pw.RowGroupSize = 128 * 1024 * 1024 //128M
	pw.PageSize = 8 * 1024              //8K
	pw.CompressionType = parquet.CompressionCodec_SNAPPY

	return fw, pw, nil
}

func CloseParquetWriter(fw source.ParquetFile, pw *writer.ParquetWriter) error {
	if err := pw.WriteStop(); err != nil {
		log.Printf("Error! %v", err)
		return err
	}
	fw.Close()
	return nil
}

func (rec DatalakeRecord) WriteJson(outfile *os.File) error {
	buff, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	outfile.WriteString(string(buff))
	outfile.WriteString("\n")
	return nil
}

func (rec JsonRecord) WriteJson(outfile *os.File) error {
	buff, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	outfile.WriteString(string(buff))
	outfile.WriteString("\n")
	return nil
}

func (rec OfflineRecord) WriteOfflineRecordAsJson(outfile *os.File) error {
	buff, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	outfile.WriteString(string(buff))
	outfile.WriteString("\n")
	return nil
}

func (rec JsonRecord) WriteCsv(outfile *os.File) error {
	in_octets1 := "<nil>"
	in_octets2 := "<nil>"
	in_octets := "<nil>"
	out_octets1 := "<nil>"
	out_octets2 := "<nil>"
	out_octets := "<nil>"
	in_rate := "<nil>"
	out_rate := "<nil>"
	in_bw := "<nil>"
	out_bw := "<nil>"
	in_err1 := "<nil>"
	in_err2 := "<nil>"
	in_err := "<nil>"

	if rec.In_octets1 != nil {
		in_octets1 = fmt.Sprintf("%d", *rec.In_octets1)
	}
	if rec.In_octets2 != nil {
		in_octets2 = fmt.Sprintf("%d", *rec.In_octets2)
	}
	if rec.In_octets != nil {
		in_octets = fmt.Sprintf("%d", *rec.In_octets)
	}

	if rec.Out_octets1 != nil {
		out_octets1 = fmt.Sprintf("%d", *rec.Out_octets1)
	}
	if rec.Out_octets2 != nil {
		out_octets2 = fmt.Sprintf("%d", *rec.Out_octets2)
	}
	if rec.Out_octets != nil {
		out_octets = fmt.Sprintf("%d", *rec.Out_octets)
	}

	if rec.In_rate != nil {
		in_rate = fmt.Sprintf("%d", *rec.In_rate)
	}
	if rec.Out_rate != nil {
		out_rate = fmt.Sprintf("%d", *rec.Out_rate)
	}
	if rec.In_bw != nil {
		in_bw = fmt.Sprintf("%.15f", *rec.In_bw)
	}
	if rec.Out_bw != nil {
		out_bw = fmt.Sprintf("%.15f", *rec.Out_bw)
	}
	if rec.In_err1 != nil {
		in_err1 = fmt.Sprintf("%d", *rec.In_err1)
	}
	if rec.In_err2 != nil {
		in_err2 = fmt.Sprintf("%d", *rec.In_err2)
	}
	if rec.In_err != nil {
		in_err = fmt.Sprintf("%d", *rec.In_err)
	}

	_, err := outfile.WriteString(fmt.Sprintf("%s|%s|%s|%d|%d|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n",
		rec.CollectTime.Format(DateTimeFormat),
		rec.Ip,
		rec.Ifindex,
		rec.Meas,
		rec.Ifspeed,
		rec.Ifoper,
		in_octets1, in_octets2, in_octets, rec.In_flg,
		out_octets1, out_octets2, out_octets, rec.Out_flg,
		in_rate, out_rate, in_bw, out_bw,
		in_err1, in_err2, in_err))
	return err
}

func (rec JsonRecord) WriteTsdb(outfile *os.File) error {
	// TSDB: <metric> <timestamp> <value> <tagk=tagv> [<tagkN=tagvN>]
	if rec.In_octets != nil {
		if rec.in_octets_tsdb_overflow {
			log.Printf("Error! TsdbOverflow: %s|%s|%s|%d", rec.Ip, rec.Ifindex, "in_octets", *rec.In_octets)
		} else {
			outfile.WriteString(fmt.Sprintf("in_octets %d %d ip=%s intf=%s\n",
				rec.CollectTime.Milliseconds(), *rec.In_octets, rec.Ip, rec.Ifindex))
		}
	}
	if rec.Out_octets != nil {
		if rec.out_octets_tsdb_overflow {
			log.Printf("Error! TsdbOverflow: %s|%s|%s|%d", rec.Ip, rec.Ifindex, "out_octets", *rec.Out_octets)
		} else {
			outfile.WriteString(fmt.Sprintf("out_octets %d %d ip=%s intf=%s\n",
				rec.CollectTime.Milliseconds(), *rec.Out_octets, rec.Ip, rec.Ifindex))
		}
	}
	if rec.In_rate != nil {
		outfile.WriteString(fmt.Sprintf("in_rate %d %d ip=%s intf=%s\n",
			rec.CollectTime.Milliseconds(), *rec.In_rate, rec.Ip, rec.Ifindex))
	}
	if rec.Out_rate != nil {
		outfile.WriteString(fmt.Sprintf("out_rate %d %d ip=%s intf=%s\n",
			rec.CollectTime.Milliseconds(), *rec.Out_rate, rec.Ip, rec.Ifindex))
	}
	if rec.In_bw != nil {
		outfile.WriteString(fmt.Sprintf("in_bw %d %.15f ip=%s intf=%s\n",
			rec.CollectTime.Milliseconds(), *rec.In_bw, rec.Ip, rec.Ifindex))
	}
	if rec.Out_bw != nil {
		outfile.WriteString(fmt.Sprintf("out_bw %d %.15f ip=%s intf=%s\n",
			rec.CollectTime.Milliseconds(), *rec.Out_bw, rec.Ip, rec.Ifindex))
	}
	if rec.In_err != nil {
		outfile.WriteString(fmt.Sprintf("in_err %d %d ip=%s intf=%s\n",
			rec.CollectTime.Milliseconds(), *rec.In_err, rec.Ip, rec.Ifindex))
	}
	return nil
}
