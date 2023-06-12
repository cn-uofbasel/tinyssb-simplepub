import json
import os
import sys
import time

import bipf
from tinyssb import keystore, util, repository, packet, node, io
import tinyssb as tiny

import base64

class Chatapp:

    def __init__ (self,name):

        if (name == "reset"):
            tiny.erase_all()
            return

        pfx = util.DATA_FOLDER + name
        if( not os.path.exists(pfx + '/_backed/config.json')):
            os.makedirs(f'{pfx}/_blob')
            os.makedirs(f'{pfx}/_logs')
            os.makedirs(f'{pfx}/_backed')

            ks = keystore.Keystore()
            self.pk = ks.new(name)

            ks.dump(pfx + '/_backed/' + util.hex(self.pk))

            with open(f"{pfx}/_backed/config.json", "w") as f:
                f.write(util.json_pp({'name': name, 'rootFeedID': util.hex(self.pk), 'id': f'@{base64.b64encode(self.pk).decode()}.ed25519'}))
            
            repo = repository.REPO(pfx, lambda feed_id, msg, sig: ks.verify(feed_id, msg, sig))
            #repo.mk_generic_log(self.pk, packet.PKTTYPE_plain48, b'log entry 1', lambda msg: ks.sign(self.pk, msg))
        else:
            with open(pfx + '/_backed/config.json') as f:
                cfg = json.load(f)
            self.pk = util.fromhex(cfg['rootFeedID'])
            ks = keystore.Keystore()
            ks.load(pfx + '/_backed/' + cfg['rootFeedID'])

            repo = repository.REPO(pfx, lambda feed_id, msg, sig: ks.verify(feed_id, msg, sig))

        faces = [io.UDP_MULTICAST(('239.5.5.8', 1558))]
        self.node = node.NODE(faces, ks, repo, self.pk, self.newEvent)

        print("id:", f'@{base64.b64encode(self.pk).decode()}.ed25519')

        # for log in self.node.repo.listlog():
        #     self.node.repo.get_log(log).set_append_cb(self.newEvent)

        self.node.start()
        self.loop()
        


    # def old_init(self, name) -> None:
    #     pfx = util.DATA_FOLDER + name
    #     if( not os.path.exists(pfx + '/_backed/config.json')):
    #         os.makedirs(f'{pfx}/_blob')
    #         os.makedirs(f'{pfx}/_logs')
    #         os.makedirs(f'{pfx}/_backed')

    #         ks = keystore.Keystore()
    #         self.pk = ks.new(name)

    #         ks.dump(pfx + '/_backed/' + util.hex(self.pk))

    #         with open(f"{pfx}/_backed/config.json", "w") as f:
    #             f.write(util.json_pp({'name': name, 'rootFeedID': util.hex(self.pk)}))
            
    #         repo = repository.REPO(pfx, lambda feed_id, msg, sig: ks.verify(feed_id, msg, sig))
    #         repo.mk_generic_log(self.pk, packet.PKTTYPE_plain48, b'log entry 1', lambda msg: ks.sign(self.pk, msg))
            
    #     else:
    #         with open(pfx + '/_backed/config.json') as f:
    #             cfg = json.load(f)
    #         self.pk = util.fromhex(cfg['rootFeedID'])
    #         ks = keystore.Keystore()
    #         ks.load(pfx + '/_backed/' + cfg['rootFeedID'])

    #         repo = repository.REPO(pfx, lambda feed_id, msg, sig: ks.verify(feed_id, msg, sig))
    
    #     faces = [io.UDP_MULTICAST(('239.5.5.8', 1558))]
    #     self.node = node.NODE(faces, ks, repo, self.pk)

    #     print("id:", f'@{base64.b64encode(self.pk).decode()}.ed25519')

    #     self.node.repo.get_log(self.pk).set_append_cb(self.newEvent)

        
    #     if (name == "Alice"):
    #         if (not os.path.exists(util.DATA_FOLDER + "Bob/_backed/config.json")):
    #             print("Bob not initialized")
    #             return
    #         with open(util.DATA_FOLDER + "Bob/_backed/config.json") as f:
    #             othercfg = json.load(f)
    #         otherfid = othercfg["rootFeedID"]
    #         if(not os.path.exists(pfx + f'/_logs/{otherfid}.log')):
    #             print("log allocated")
    #             repo.allocate_log(bytes.fromhex(otherfid),0,bytes.fromhex(otherfid)[:20])
    #         other = repo.get_log(bytes.fromhex(otherfid))
    #     elif (name == "Bob" ):
    #         if (not os.path.exists(util.DATA_FOLDER + "Alice/_backed/config.json")):
    #             print("Alice not initialized")
    #             return
    #         with open(util.DATA_FOLDER + "Alice/_backed/config.json") as f:
    #             othercfg = json.load(f)
    #         otherfid = othercfg["rootFeedID"]

    #         if(not os.path.exists(pfx + f'/_logs/{otherfid}.log')):
    #             print("log allocated")
    #             repo.allocate_log(bytes.fromhex(otherfid),0,bytes.fromhex(otherfid)[:20])
    #         other = repo.get_log(bytes.fromhex(otherfid))
        
    #     print("other:", util.hex(other.fid))
    #     self.node.activate_log(other.fid,node.LOGTYPE_remote)
    #     other.subscription += 1
    #     other.set_append_cb(self.newEvent)
    #     print("sub:", other.subscription)
    #     for log in self.node.repo.listlog():
    #         self.node.repo.get_log(log).set_append_cb(self.newEvent)
    #     self.node.start()
    #     self.loop()



    def backend(self, data):
        data = bipf.dumps(data)

        if len(data) > 48:
            self.node.write_blob_chain(self.pk, data)
        else:
            data += bytes(48 - len(data))
            self.node.write_typed_48B(self.pk, data, packet.PKTTYPE_plain48)

    def newEvent(self, pkt):
        print("NEW CHAT:")
        buf = pkt.get_content()
        if buf:
            print(pkt.get_content())
            print(bipf.loads(pkt.get_content()))
        else:
            print("received null")

    def loop(self): #9cf59d63d66ba33d98d6a5bd083716ea14e59e23700852a2ddae78081f7a3b09
        while True:
            inp = input(">")
            if (inp.lower() == "/exit"):
                break
            if inp.startswith("/long"):
                message = ["TAV", "Das ist eine Nachricht die so lange ist, dass sie in mehreren Blobs versendet werden muss", None, int(time.time()/1000)]
                self.backend(message)
                continue
            if inp.startswith("/sub"):
                cmd = inp.split(" ")
                print("subscribing to", cmd[1])
                self.node.activate_log(bytes.fromhex(cmd[1]), node.LOGTYPE_remote) #, bytes.fromhex(cmd[1])[:20]
                for log in self.node.repo.listlog():
                    self.node.repo.get_log(log).set_append_cb(self.newEvent)
            message = ["TAV", inp, None, int(time.time())]
            self.backend(message)

if __name__ == '__main__':
    Chatapp(sys.argv[1])
