# tinySSB Simple Pub

The "tinySSB simple pub" offers an Internet-based storage area for tinySSB append-only logs:
- accessible via web sockets
- running the tinySSB synchronization protocol
  -  datagram-based, packets have 120 Bytes or less
  -  growOnlySet protocol for compressing feed IDs
  -  vectors with HAVE and NEED information, as well as requesting chunks (sidechain content)

The simple pub lacks:
- metadata privacy (no secure handshake protocol in place)
- access control (no read-only version: every device can add to the grow-only set)
- feed management (removing obsolete feeds)
- per end-device grow-only set (only one global table of feed IDs)
- resilience (DHT-like self-reconfiguration)

## Internal Structure

- Python and Flask
- file system layout: ...

---

## Demo version 0.0.1

Procedure:
1. install flask and flask_sockets with pip
2. run `python server.py` with no argument
3. run `python client.py` with any string as argument

Outcome:
- The client create a TinySSB identity and a packet with the received string as payload
- The client sends the packet
- The server receives it, prints the payload and sends back the whole packet
- The client parses the packet, checks the signature (with the stored credentials) and prints the payload

Further:
- `client.py` arg is optional
- Running `flask --app server run --debug --port=8080` instead of `python server.py` takes advantages of the flask debugger which updates the server automatically when the file is updated