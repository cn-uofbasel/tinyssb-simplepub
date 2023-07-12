import asyncio
from websockets.server import serve

import tinyssb.packet as packet
import tinyssb.keystore as keystore
import bipf

HTTP_PORT = 8080

async def echo(websocket):
    ks = keystore.Keystore()
    async for message in websocket:
        fid = bytes(message[8:40])
        # print(f"Type = {type(fid)} + {message}")
        # pkt = packet.PACKET(fid, 1, fid[:20])
        p = packet.from_bytes(message, fid, 1, fid[:20], lambda fid, mssg, sig: ks.verify(fid, mssg, sig))
        received = p.get_content().split(b'\x00')[0]
        print(f"\nReceived {received[32:]}")

        await websocket.send(message)

async def main():
    async with serve(echo, "localhost", HTTP_PORT):
        await asyncio.Future()  # run forever

asyncio.run(main())