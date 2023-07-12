# tinySSB Simple Pub

The "tinySSB simple pub" offers an Internet-based storage area for tinySSB append-only logs:
- accessible via web sockets
- running the tinySSB synchronization protocol
  -  datagram-based, packets have 120 Bytes or less
  -  growOnlySet protocol for compressing feed IDs
  -  vectors with WANT and CHNK (request) information
- adaptive timers, made for reliable connections
- crash resistant: the ```frontier.bin``` file for a log is updated on startup, should the log have been extended but the frontier failed to be updated

The simple pub lacks:
- metadata privacy (no secure handshake protocol in place)
- access control (no read-only version: every device can add to the grow-only set)
- feed management (removing obsolete feeds)
- per end-device grow-only set (only one global table of feed IDs)
- resilience (DHT-like self-reconfiguration)

The software has been heavily rewritten
- new experimental file system layout: only two files per log
  - the ```log.bin``` file contains for each entry its full length sidechain even if not all chunks have been received yet
  - the ```frontier.bin``` file stores essential properties, including a list of unfinished sidechains
  - by persisting sidechain status we avoid a rescan of the file system
- no main loop anymore for handling all IO. Instead we adopt the asyncio model of the ```websockets``` package and have three different tasks:
  - goset
  - WANT vector
  - CHNK vector
- no dependency on other tinySSB packages: BIPF and pure25519 is included

## Programs

### ```spub.py``` - a pure peer pub: can be both initiator and responder

```
usage: spub.py [-h] [-d DATAPATH] [-role {in,inout,out}] [-v] [uri_or_port]

positional arguments:
  uri_or_port           TCP port if responder, URI if intiator (default is ws://127.0.0.1:8080)

options:
  -h, --help            show this help message and exit
  -d DATAPATH           path to persistency directory
  -role {in,inout,out}  direction of data flow (default: in)
  -v                    print i/o timestamps
```

Examples for starting the tinySSB SimplePub
```
% ./spub.py -r out 8080                    # read-only responder on websocket port 8080

% ./spub.py -r inout 8080                  # fully replicating pub responder

% ./spub.py -d data2 ws://127.0.0.1:8080   # download-only initiator
```


### ```frontier.py``` - displays the content of the persistence directory (including un-BIPF-ing where possible)

```
usage: frontier.py [-h] [-d DATAPATH] [-s]

options:
  -h, --help   show this help message and exit
  -d DATAPATH  path to persistency directory
  -s           only show stats (no content), default: False
```

Example
```
% ./frontier.py -d data -s
Stats:
- 23 feeds
- 147 available entries
- 261 available chunks
- 36 missing chunks: 1.6.32ff, 1.7.0ff
```

----
