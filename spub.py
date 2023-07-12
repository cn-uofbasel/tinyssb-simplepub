#!/usr/bin/env python3

# new_server.py
# tinySSB simplepub websocket server

import asyncio
import hashlib
import signal
import sys
import time
import traceback
import websockets

WS_PORT = 8080

import simplepub.node

# ---------------------------------------------------------------------------

start_time = None

i_pkt_cnt = 0
o_pkt_cnt = 0

def nowstr():
    global start_time
    t = time.time()
    if start_time == None:
        start_time = t
    t -= start_time
    ms = str(int(1000*(t+1)))[-3:]
    return f"{int(t)}.{ms}"

async def launch_adv(wsock, get_adv_fct, args):
    global o_pkt_cnt
    while True:
        pkts, tout = get_adv_fct()
        for p in pkts:
            o_pkt_cnt += 1
            if args.v:
                print(f">> o={o_pkt_cnt} {nowstr()}: {len(p)}B 0x{p[:32].hex()}..")
            await wsock.send(p)
        await asyncio.sleep(tout)
        
async def onConnect(wsock, node, args):
    global i_pkt_cnt, o_pkt_cnt
    if args.v: print("-- connection up")
    tasks = [ asyncio.create_task(launch_adv(wsock,fct,args)) for fct in
              [ lambda: node.get_entry_adv(),
                lambda: node.get_chain_adv(),
                lambda: node.get_GOset_adv() ] ]
    pkt_cnt = 0
    while True:
        try:
            pkt = await wsock.recv()
            i_pkt_cnt += 1
            if args.v:
                print(f"<< i={id(asyncio.current_task())}.{i_pkt_cnt} @{nowstr()}: {len(pkt)}B 0x{pkt[:20].hex()}.. h={hashlib.sha256(pkt).digest()[:10].hex()}..")
            for p in node.rx(pkt):
                o_pkt_cnt += 1
                if args.v:
                    print(f">> o={o_pkt_cnt} {nowstr()}: {len(p)}B 0x{p[:32].hex()}..")
                await wsock.send(p)
            await asyncio.sleep(0)
        except (websockets.exceptions.ConnectionClosedOK,
                websockets.exceptions.ConnectionClosedError):
            break
        except Exception as e:
            traceback.print_exc()
            break
    for t in tasks:
        try:    t.cancel()
        except: pass
    if args.v:
        print("-- connection down")

async def main(args):
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    node = simplepub.node.PubNode(args.d, args.role, args.v)

    try:
        if type(args.uri_or_port) == int:
            print(f"Starting responder on port {args.uri_or_port}")
            async with websockets.serve(lambda s: onConnect(s, node, args),
                                        "0.0.0.0", args.uri_or_port):
                await stop
        else:
            print(f"Connecting to {args.uri_or_port}")
            async with websockets.connect(args.uri_or_port) as wsock:
                await onConnect(wsock, node, args)
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        pass

# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument('-d', type=str, default='./data', metavar='DATAPATH',
                    help='path to persistency directory')
    ap.add_argument('-role', choices=['in','inout','out'], default='in',
                    help='direction of data flow (default: in)')
    ap.add_argument('uri_or_port', type=str, nargs='?',
                    default='ws://127.0.0.1:8080',
                    help='TCP port if responder, URI if intiator (default is ws://127.0.0.1:8080)')
    ap.add_argument('-v', action='store_true', default=False,
                    help='print i/o timestamps')
    
    args = ap.parse_args()
    if args.uri_or_port.isdigit():
        args.uri_or_port = int(args.uri_or_port)

    asyncio.run(main(args))

# eof
