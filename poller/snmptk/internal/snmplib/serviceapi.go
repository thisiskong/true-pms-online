package snmplib

import (
	"bytes"
	"encoding/xml"
	"fmt"
	"io"
	"io/ioutil"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type DiscQrunL1 struct {
	device    string  // device name
	latitude  float64 // OLT_LATITUDE
	longitude float64 // OLT_LONGITUDE
	ponports  map[string]DiscQrunL1PonPort
}

type DiscQrunL1PonPort struct {
	device          string  // device name
	ponport         string  // PON_PORT_NO
	l1name          string  // SPL1_NAME
	l1_dl_max_bw    string  // L1_DL_MAX_BW
	l1_ul_max_bw    string  // L1_UL_MAX_BW
	dl_bw_remaining string  // DOWNLOAD_BW_REMAINING
	ul_bw_remaining string  // UPLOAD_BW_REMAINING
	latitude        float64 // SPL1_LATITUDE
	longitude       float64 // SPL1_LONGITUDE
}

type Spl1Info struct {
	OLT_VENDOR           string     `json:"OLT_VENDOR"`
	OLT_MODEL            string     `json:"OLT_MODEL"`
	OLT_REMARK           string     `json:"OLT_REMARK"`
	OLT_IP_ADDR          string     `json:"OLT_IP_ADDR"`
	OLT_LATITUDE         string     `json:"OLT_LATITUDE"`
	OLT_LONGITUDE        string     `json:"OLT_LONGITUDE"`
	OLT_SERVICE_STATE    string     `json:"OLT_SERVICE_STATE"`
	OLT_RUNNING_STATE    string     `json:"OLT_RUNNING_STATE"`
	OLT_INTERFACE_UPLINK string     `json:"OLT_INTERFACE_UPLINK"`
	OLT_MAX_SPEED        string     `json:"OLT_MAX_SPEED"`
	UPLOAD_MAX_SPEED     string     `json:"UPLOAD_MAX_SPEED"`
	SMALL_POCKET         string     `json:"SMALL_POCKET"`
	IOP_FUNCTION         string     `json:"IOP_FUNCTION"`
	GET_SPL1             []Spl1Item `json:"GET_SPL1"`
}

type Spl1Item struct {
	OLT_CARD_TYPE         string `json:"OLT_CARD_TYPE"`
	PON_PORT_NO           string `json:"PON_PORT_NO"`
	SPL1_NO               string `json:"SPL1_NO"`
	SPL1_NAME             string `json:"SPL1_NAME"`
	L1_DL_MAX_BW          string `json:"L1_DL_MAX_BW"`
	L1_UL_MAX_BW          string `json:"L1_UL_MAX_BW"`
	DOWNLOAD_BW_REMAINING string `json:"DOWNLOAD_BW_REMAINING"`
	UPLOAD_BW_REMAINING   string `json:"UPLOAD_BW_REMAINING"`
	SPL1_LATITUDE         string `json:"SPL1_LATITUDE"`
	SPL1_LONGITUDE        string `json:"SPL1_LONGITUDE"`
}

func getWsdl(config *ServiceApi) error {
	// url := "http://172.19.208.107:7105/axis2/services/IM4GisService?wsdl"
	url := fmt.Sprintf("%s?wsdl", config.Endpoint)
	resp, err := http.Get(url)
	if err != nil {
		panic(err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	log.Printf("%s", body)
	return nil
}

func getSpl1(config *ServiceApi, name string) (*Spl1Info, error) {
	t := time.Now()
	// Production: 	http://10.50.25.128:7105/axis2/services/IM4GisService?wsdl
	// Development: http://172.19.208.107:7105/axis2/services/IM4GisService?wsdl
	xmldata := fmt.Sprintf(`<soapenv:Envelope
									xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
									xmlns:_4g="http://oss.zsmart.ztesoft.com/rm/webservice/types/_4gis/">
								<soapenv:Header/>
								<soapenv:Body>
										<_4g:GetSpl1InParams>
											<!--Optional:-->
											<!--<OLT_NUMBER>?</OLT_NUMBER>-->
											<!--Optional:-->
											<OLT_NAME>%s</OLT_NAME>
										</_4g:GetSpl1InParams>
								</soapenv:Body>
							</soapenv:Envelope>`, name)

	data := []byte(xmldata)
	client := &http.Client{Timeout: time.Duration(config.Timeout) * time.Second}
	req, err := http.NewRequest("POST", config.Endpoint, bytes.NewBuffer(data))
	if err != nil {
		log.Printf("Error: GetSpl1: %s, %s", name, err)
		return nil, err
	}
	req.Header.Add("Content-Type", "text/xml; charset=utf-8")

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		log.Printf("Error: GetSpl1: %s, %s", name, err)
		return nil, err
	}

	gponInfo, err := parseGetSpl1(string(body))
	log.Printf("GetSpl1: %s return in %s", name, time.Since(t))
	return gponInfo, err
}

func parseGetSpl1(xmldata string) (*Spl1Info, error) {
	r := strings.NewReader(xmldata)
	parser := xml.NewDecoder(r)
	depth := 0
	tagname := ""

	spl1Info := &Spl1Info{}
	spl1List := make([]Spl1Item, 0)
	spl1 := Spl1Item{}

	// status := "" // STATUS_CD
	// errmsg := "" // ERROR_MESSAGE
	for {
		token, err := parser.Token()
		if err != nil {
			//EOF
			break
		}
		switch t := token.(type) {
		case xml.StartElement:
			elmt := xml.StartElement(t)
			name := elmt.Name.Local
			// log.Printf("%s", name)
			// printElmt(name, depth)
			tagname = name
			// names = append(names, name)
			depth++
			if name == "GET_SPL1" || name == "GET_SPL0" {
				spl1 = Spl1Item{}
			}
		case xml.EndElement:
			depth--
			elmt := xml.EndElement(t)
			name := elmt.Name.Local
			if name == "GET_SPL1" || name == "GET_SPL0" {
				spl1List = append(spl1List, spl1)
			}
			tagname = ""
		case xml.CharData:
			bytes := xml.CharData(t)
			value := strings.TrimSpace(string([]byte(bytes)))
			switch tagname {
			case "ERROR_MESSAGE":
				if value != "success" {
					return nil, fmt.Errorf("error: %s", value)
				}
			case "OLT_VENDOR":
				spl1Info.OLT_VENDOR = value
			case "OLT_MODEL":
				spl1Info.OLT_MODEL = value
			case "OLT_REMARK":
				spl1Info.OLT_REMARK = value
			case "OLT_IP_ADDR":
				spl1Info.OLT_IP_ADDR = value
			case "OLT_LATITUDE":
				spl1Info.OLT_LATITUDE = value
			case "OLT_LONGITUDE":
				spl1Info.OLT_LONGITUDE = value
			case "OLT_SERVICE_STATE":
				spl1Info.OLT_SERVICE_STATE = value
			case "OLT_RUNNING_STATE":
				spl1Info.OLT_RUNNING_STATE = value
			case "OLT_INTERFACE_UPLINK":
				spl1Info.OLT_INTERFACE_UPLINK = value
			case "OLT_MAX_SPEED":
				spl1Info.OLT_MAX_SPEED = value
			case "UPLOAD_MAX_SPEED":
				spl1Info.UPLOAD_MAX_SPEED = value
			case "SMALL_POCKET":
				spl1Info.SMALL_POCKET = value
			case "IOP_FUNCTION":
				spl1Info.IOP_FUNCTION = value

			// SPL1
			case "OLT_CARD_TYPE":
				spl1.OLT_CARD_TYPE = value
			case "PON_PORT_NO":
				spl1.PON_PORT_NO = value
			case "SPL1_NO":
				spl1.SPL1_NO = value
			case "SPL1_NAME":
				spl1.SPL1_NAME = value
			case "L1_DL_MAX_BW":
				spl1.L1_DL_MAX_BW = value
			case "L1_UL_MAX_BW":
				spl1.L1_UL_MAX_BW = value
			case "DOWNLOAD_BW_REMAINING":
				spl1.DOWNLOAD_BW_REMAINING = value
			case "UPLOAD_BW_REMAINING":
				spl1.UPLOAD_BW_REMAINING = value
			case "SPL1_LATITUDE":
				spl1.SPL1_LATITUDE = value
			case "SPL1_LONGITUDE":
				spl1.SPL1_LONGITUDE = value
			}
		}
	}
	(*spl1Info).GET_SPL1 = spl1List
	return spl1Info, nil
}

func getL1Splitter(config *ServiceApi, deviceInst *Device) (DiscQrunL1, error) {
	discQrunL1 := DiscQrunL1{
		ponports: make(map[string]DiscQrunL1PonPort),
	}
	spl1Info, err := getSpl1(config, deviceInst.SysName)
	if err != nil {
		log.Printf("Error: getL1Splitter: %s [%v]", deviceInst.SysName, err)
		return discQrunL1, err
	}

	// if debug {
	// 	s, _ := json.MarshalIndent(spl1Info, "", " ")
	// 	log.Printf("getL1Splitter = %s", string(s))
	// }

	// device.latitude & device.longitude
	latitude, _ := strconv.ParseFloat(spl1Info.OLT_LATITUDE, 64)
	longitude, _ := strconv.ParseFloat(spl1Info.OLT_LONGITUDE, 64)

	discQrunL1.latitude = latitude
	discQrunL1.longitude = longitude

	// convert to map lookup by portPort
	for _, item := range spl1Info.GET_SPL1 {
		// device.latitude & device.longitude
		l1_latitude, _ := strconv.ParseFloat(item.SPL1_LATITUDE, 64)
		l1_longitude, _ := strconv.ParseFloat(item.SPL1_LONGITUDE, 64)

		discQrunL1.ponports[item.PON_PORT_NO] = DiscQrunL1PonPort{
			device:          deviceInst.SysName,
			ponport:         item.PON_PORT_NO,
			l1name:          item.SPL1_NAME,
			l1_dl_max_bw:    item.L1_DL_MAX_BW,
			l1_ul_max_bw:    item.L1_UL_MAX_BW,
			dl_bw_remaining: item.DOWNLOAD_BW_REMAINING,
			ul_bw_remaining: item.UPLOAD_BW_REMAINING,
			latitude:        l1_latitude,
			longitude:       l1_longitude,
		}
	}
	return discQrunL1, nil
}

func MapL1Splitter(config *DiscoveryConfig, lookupService *LookupService, deviceInst *Device) error {
	if config.Discovery.ServiceApi.Endpoint == "" {
		// disable
		return nil
	}

	discl1Device, err := getL1Splitter(&config.Discovery.ServiceApi, deviceInst)
	if err != nil {
		// API error, try load data from db: disc_qrun_l1
		discl1Device, err = lookupService.loadDiscQrunL1(deviceInst.SysName)
		if err != nil {
			log.Printf("Error: %v", err)
			return err
		}
	} else {
		// API call successful, save data
		err := lookupService.saveDiscQrunL1(deviceInst.SysName, discl1Device)
		if err != nil {
			log.Printf("Error: %v", err)
			return err
		}
	}

	deviceInst.Latitude = discl1Device.latitude
	deviceInst.Longitude = discl1Device.longitude

	for i, intf := range deviceInst.Interfaces {
		if intf.Save && intf.PonPort != "" {
			item, ok := discl1Device.ponports[intf.PonPort]
			if ok {
				log.Printf("MapL1Splitter: %s = %s|%v|%v|%v|%v", intf.PonPort, item.l1name, item.l1_dl_max_bw, item.l1_ul_max_bw, item.dl_bw_remaining, item.ul_bw_remaining)
				deviceInst.Interfaces[i].L1_SPLT = item.l1name
				deviceInst.Interfaces[i].L1_DL_MAX_BW = item.l1_dl_max_bw
				deviceInst.Interfaces[i].L1_UL_MAX_BW = item.l1_ul_max_bw
				deviceInst.Interfaces[i].DL_BW_REMAINING = item.dl_bw_remaining
				deviceInst.Interfaces[i].UL_BW_REMAINING = item.ul_bw_remaining
			} else {
				log.Printf("MapL1Splitter: %s = NotFound", intf.PonPort)
			}
		}
	}
	return nil
}
