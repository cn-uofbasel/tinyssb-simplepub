import _thread
import base64
import json
import os
import time

from tinyssb import keystore, util, repository, node, io

class WebServer:

    def __init__(self):

        name = "server"
        pfx = util.DATA_FOLDER + name
        if not os.path.exists(pfx + '/_backed/config.json'):
            os.makedirs(f'{pfx}/_blob')
            os.makedirs(f'{pfx}/_logs')
            os.makedirs(f'{pfx}/_backed')

            ks = keystore.Keystore()
            self.pk = ks.new(name)

            ks.dump(pfx + '/_backed/' + util.hex(self.pk))

            with open(f"{pfx}/_backed/config.json", "w") as f:
                f.write(util.json_pp({ 'name': name, 'rootFeedID': util.hex(self.pk),
                                       'id': f'@{base64.b64encode(self.pk).decode()}.ed25519' }))

            repo = repository.REPO(pfx,
                                   lambda feed_id, msg, sig: ks.verify(feed_id, msg, sig))
        else:
            with open(pfx + '/_backed/config.json') as f:
                cfg = json.load(f)
            self.pk = util.fromhex(cfg['rootFeedID'])
            ks = keystore.Keystore()
            ks.load(pfx + '/_backed/' + cfg['rootFeedID'])

            repo = repository.REPO(pfx,
                                   lambda feed_id, msg, sig: ks.verify(feed_id, msg, sig))

        faces = [io.WS("0.0.0.0")]
        self.send_thread(faces[0])
        self.node = node.NODE(faces, ks, repo, self.pk, None)

        print("id:", f'@{base64.b64encode(self.pk).decode()}.ed25519')

        self.node.start()
        while True:
            # d = b'Trying to reach you'
            # d += b'\x00' * (48 - len(d))
            # self.node.write_plain_48B(self.node.me, d)
            time.sleep(3)

    def send_thread(self, f):
        _thread.start_new_thread(f.start_send, tuple())
        _thread.start_new_thread(f.start, tuple())

if __name__ == '__main__':
    WebServer()
