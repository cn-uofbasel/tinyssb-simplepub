# Thoughts and Questions
This file is outdated (2022-09-02)
@author Etienne Mettaz

## Abstract

While preparing a final version of TinySSB, I write here the questions popping
into my mind to find answers later (or ask for them)
Warnings are implementation remarks to discuss, problems are tasks for myself
while the last section is on past or current misunderstandings from my side that
I want to keep track of.

## Questions

### New

1. in node::incoming_logentry, there is a 'nd' in a lambda function. I don't
   know where it is defined and it throws errors... (see fixme)
2. In my api::\_\_main__, why does only one peer (David) receives packets from the
   other? Try to add want and blob request messages
3. node::request_latest (see fixme)

### Old

1. Should we describe a packet as having 120 or 128 bytes?
   [120B]
2. The "acknowledge" packet is not properly and consistently used I think, what
   might cause problems: in `session.py`, `SlidingWindow::_process()`, we create
   the ack packet, whose content is only the id of the feed whose action is
   acknowledged and some zero bytes (for padding). Couldn't that lead to
   misunderstanding by acknowledging the wrong packet (for example if the remote
   makes several children in a row and one make_child packet is lost)? Maybe
   that's our " concurrency problem"...
3. In `btc_var_int(i)` and `btc_var_int_decode(buf)`, length are bounded (total
   length must fit within 3 bytes), but a blob could theoretically be
   arbitrarily long. Shouldn't we use the version from bipf-python
   `varint_decode()` and `varint_encode()` that uses a loop?
   [Not the same!!! BIPF is better]

## Former Problems (not relevant anymore):

1. [DONE] repo.get_log and repo.get_blob are not equivalent at all [fetch_blob]
2. The request packets ('blobs' and 'want') are not part of the feed by itself.
   Should they nevertheless be described in the documentation?
   [Correct, create a point in doc and let him document that]
3. The `log_burning_demo.py` does a lot of non-trivial work, and people using
   the library will need to do it as well. What interface do we want to give to
   the users? [ Good luck ;)]
4. I don't think `Keystore::dump()` and `Keystore::load()` are ever called. It
   makes the code non-reentrant, as we don't keep track of the sub-feeds key
   pairs
   [Not yet, but good think (next poc)]
5. Repo::mk_child_log() specification says that last 12 bytes of
   'PKTTYPE_ischild'(and of 'PKTTYPE_iscontn') = hash(fid[seq]) (fid and seq
   from referenced packet from other feed), but here we use the last 12B of the
   (64B) signature. [He looks]
6. There's nothing in the documentation on the format of the packets as stored
   in the disk (as specified in REPO::allocate_log() and LOG::). Should I add
   it? [Try to understand and write, but only first log]
7. The "acknowledge" packet is not properly and consistently used I think, what
   might cause problems:
    1. in `session.py`, `SlidingWindow::_process()`, we create the ack packet,
       whose content is only the id of the feed whose action is acknowledged and
       some zero bytes (for padding). Couldn't that lead to misunderstanding by
       acknowledging the wrong packet (for example if the remote makes several
       children in a row and one make_child packet is lost)? Maybe that's our "
       concurrency problem"...
    2. [Fixed] Also, the condition for the if-loop is not exactly the same:

       ```if pkt.typ == bytes([packet.PKTTYPE_contdas]):```

       vs

       ```if pkt.typ[0] == packet.PKTTYPE_iscontn:```
    3. What happens if a `mk_child` is lost? There are currently no
       acknowledgment for that.
       [No ack for children. SSB doesn't get lost]
8. [SOLVED] Prefix:
    1. In code, `nam` does not contain prefix (`VERSION`),
       unlike `LOG_ENTRY_NAME` in packet-spec.md
    2. It is added to compute dmx, but **not for signature**
    3. `VERSION = b'tinyssb-v0'` => prefix.size != 8 bytes
9. poc-04: amount of files in data/'user'/_logs always grows
10. [SOLVED] LOG.write_typed_48B() (in repository.py) has same sig as
    NODE.write_typed_48B()
    I find it a bit confusing PS: session also contains
    SlidingWindow.write_typed_48B()
11. [SOLVED] Can we end a feed by declaring it as continued (packet type 5) with
    continuation feedID set to 0?
    Yes: repo::write_eof()

12. [SOLVED] Packet fields in packet-spec.md do not always correspond to the
    names in code
13. [SOLVED] True or false: a continued feed is always closed
14. Sometime, the number of logs increases linearly. Problem with deleting? Or
    verifying DMX/SIG?

## Questions / remarks for myself

1. [SOLVED] About poc-03: The only diff between PKTTYPE_ischild and
   PKTTYPE_iscontn is
   that feedID refers to a parent or not (horizontal). How do we tell them
   apart? With Type field
   (same for mkchild and contdas)
2. [SOLVED] Why multiple feeds and subfeed? having a sliding window on just the
   main feed
   lets us do everything we want, no?
    1. multiple feeds let a user have different activities and other peers
       replicate just a subset of them
    2. Continuation feeds simplifies greatly the management of the sliding
       window
       (starts always at the start of the current feed and ends at the actual
       point, discarded are always entire feeds)
3. [SOLVED] `neigh` is not defined in IOLOOP.run(), but used later. I'm not sure
   what it
   is and I wonder if I didn't miss something.
4. [SOLVED] fix REPO.verify
5. [SOLVED] compare with poc-04 (and 3?)
6. [SOLVED] Diff between log, blob, plain (incl. type)
7. [SOLVED] Is a "log" a packet from format "DMX+TYP+PAYL+SIG" or a packet with
   TYP=1? Is
   the first packet of a blob chain considered to be a Log or Blob entry?

## Documentation

Things not to forget in final documentation

1. packet type (see end of packet.py)
2. list of packet fields (see beginning of packet.py)
3. Add packet fields description for blob packets
4. comments at the end of repository (poc-01)
5. Check PREV of 1. packet

General packet layout:

1. add other entry types
2. list of "algorithm and type fields"

___

1. Short description, rationale and link to SSB % packet length, with
   description of rationale and SSB-history
2. Packet types and tree structure
3. Relevant fields
4. Logs entries
5. Blob entries
6. special entries
