package snmplib

import (
	"errors"
	"log"
	"sort"
	"strings"
	"time"

	"github.com/go-zookeeper/zk"
)

func zkGetActiveHost(setting *AppSetting) (map[string]bool, error) {

	servers := strings.Split(setting.Zk.Host, ",")
	timeout := time.Duration(setting.Zk.Timeout) * time.Second
	zkConn, _, err := zk.Connect(servers, timeout)
	if err != nil {
		return nil, err
	}

	//	+ /pms/online
	//	+ /pms/online/seq/{seq_number}
	//	+ /pms/online/host/{hostname}
	children, _, err := zkConn.Children("/pms/online/host")
	if err != nil {
		return nil, err
	}
	aliveHost := make(map[string]bool)
	for _, host := range children {
		aliveHost[host] = true
	}
	return aliveHost, nil
}

func GetMySeqNumber(zkConn *zk.Conn, resource string, zkNode string) (int, int, error) {
	// return (cid, csize)
	children, _, err := zkConn.Children(resource)
	log.Printf("GetChildren: %v, ret=%v, err=%v", resource, children, err)
	if err != nil {
		return -1, -1, err
	}

	sort.Strings(children)
	index := -1
	for idx, val := range children {
		zkPath := resource + "/" + val
		// log.Printf("zkPath=%v, zkNode=%v, idx=%d", zkPath, zkNode, idx)
		if zkPath == zkNode {
			index = idx
			break
		}
	}
	log.Printf("GetMySeqNumber: %v, ret=%v, index=%d", resource, children, index)
	if index == -1 {
		return -1, -1, errors.New("index not found")
	}
	return index, len(children), nil
}

// func CreateZkNode(zkConn *zk.Conn, resource string) (*string, error) {
// 	// create following zkNodes
// 	//	+ /pms/online
// 	//	+ /pms/online/seq/{seq_number}
// 	//	+ /pms/online/host/{hostname}
// 	entries := strings.Split(resource, "/")
// 	for idx := range entries {
// 		if idx > 0 {
// 			zkPath := strings.Join(entries[:idx+1], "/")
// 			zkNode, err := zkConn.Create(zkPath, []byte(""), 0, zk.WorldACL(zk.PermAll))
// 			log.Printf("CreateZkNode: %v, ret=%v, err=%v", zkPath, zkNode, err)
// 			// ignore error here as it could be due to parent node already exist
// 		}
// 	}

// 	hostname, _ := os.Hostname()
// 	zkPath := resource + "/" + hostname + "."
// 	zkChildNode, err := zkConn.Create(zkPath, []byte(""), zk.FlagSequence|zk.FlagEphemeral, zk.WorldACL(zk.PermAll))
// 	log.Printf("CreateZkNode: %v, ret=%v, err=%v", zkPath, zkChildNode, err)
// 	if err != nil {
// 		return nil, err
// 	}
// 	return &zkChildNode, nil
// }

// func WatchChildren(zkConn *zk.Conn, resource string) {
// 	var done = make(chan bool)
// 	for {
// 		err := addWatch(zkConn, resource)
// 		if err != nil {
// 			break
// 		} else {
// 			time.Sleep(time.Second)
// 		}
// 	}
// 	<-done
// }

// func addWatch(zkConn *zk.Conn, resource string) error {
// 	log.Printf("addWatch: %v", resource)
// 	children, stat, ch, err := zkConn.ChildrenW(resource)
// 	if err != nil {
// 		log.Printf("addWatch Error: %v", err)
// 		return err
// 	}
// 	log.Printf("%+v %+v\n", children, stat)
// 	var done = make(chan bool)
// 	go func() {
// 		for {
// 			select {
// 			case evt, ok := <-ch:
// 				if !ok {
// 					return
// 				}
// 				// log.Println("Received event:", evt)
// 				if evt.Type == zk.EventNodeChildrenChanged {
// 					log.Println("Received event:", evt)
// 					close(done)
// 				}
// 			}
// 		}
// 	}()
// 	<-done
// 	return nil
// }
