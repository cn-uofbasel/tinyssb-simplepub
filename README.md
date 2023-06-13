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
