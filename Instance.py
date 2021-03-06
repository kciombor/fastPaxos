import sys
from typing import Optional

import jsonpickle
from flask import Flask, request, abort

from src.Acceptor import Acceptor
from src.Learner import Learner
from src.Message import PrepareMessage, AcceptMessage, AckMessage, \
    AckValueMessage
from src.Paxos import get_fast_quorum_size
from src.Proposer import Proposer
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
instance = None  # initialized in main


@app.before_request
def check_status():
    if request.path in ['/reset', '/poison', '/kill']:
        return

    instance.request_count += 1
    if instance.dying and instance.request_count > 6:
        instance.set_active(False)

    if instance.get_active() is False:
        abort(404)


@app.route('/heartbeat', methods=['GET'])
def heartbeat():
    if instance.get_active() is True:
        return "Instance with quorum: " + str(instance.quorum_size), 200
    else:
        abort(404)


@app.route('/propose_value', methods=['POST'])
def propose_value():
    value = request.values.get('value')
    instance.propose_value(value)
    return '', 200


@app.route('/prepare', methods=['POST'])
def prepare():
    prepare_msg = instance.prepare()
    return jsonpickle.encode(prepare_msg), 200


@app.route('/receive_prepare', methods=['POST'])
def receive_prepare():
    msg_json = request.values.get('prepare_msg')
    msg = jsonpickle.decode(msg_json)
    ack_msg = instance.receive_prepare(msg)
    return jsonpickle.encode(ack_msg), 200


@app.route('/receive_ack', methods=['POST'])
def receive_ack_message():
    msg_json = request.values.get('ack_msg')
    msg = jsonpickle.decode(msg_json)
    acc_msg = instance.receive_ack_message(msg)
    if acc_msg:
        return jsonpickle.encode(acc_msg), 200
    else:
        abort(422)


@app.route('/receive_request', methods=['POST'])
def receive_fast_request():
    value = request.values.get('value')
    ack_value_msg = instance.receive_request(value)
    if ack_value_msg:
        return jsonpickle.encode(ack_value_msg), 200
    else:
        abort(422)


@app.route('/receive_acc', methods=['POST'])
def receive_acc_message():
    msg_json = request.values.get('acc_msg')
    msg = jsonpickle.decode(msg_json)
    ack_value = instance.receive_accept(msg)
    return jsonpickle.encode(ack_value), 200


@app.route('/receive_ack_value', methods=['POST'])
def receive_ack_value_message():
    msg_json = request.values.get('ack_value_msg')
    msg = jsonpickle.decode(msg_json)
    instance.receive_accepted(msg)
    return '', 200


@app.route('/get_learned_value', methods=['GET'])
def get_learned_value():
    value = instance.learner.learned_value
    print("Learned value: {}".format(value))
    if value:
        return str(value), 200
    else:
        abort(404)


@app.route('/reset', methods=['GET'])
def reset():
    instance.request_count = 0
    instance.dying = False
    instance.set_active(True)
    instance.reset()
    return '', 200


@app.route('/kill', methods=['GET'])
def kill():
    instance.set_active(False)
    instance.dying = False
    instance.request_count = 0
    return '', 200


@app.route('/poison', methods=['GET'])
def poison():
    instance.dying = True
    instance.request_count = 0
    instance.set_active(True)
    return '', 200


class Instance(object):
    active = True  # type: bool

    def __init__(self, uid: str, quorum_size: int) -> None:
        self.uid = uid
        self.quorum_size = quorum_size
        self.proposer = Proposer(self.uid, self.quorum_size)
        self.acceptor = Acceptor(self.uid)
        self.learner = Learner(self.uid, self.quorum_size)
        self.request_count = 0
        self.dying = False

    def reset(self):
        self.proposer = Proposer(self.uid, self.quorum_size)
        self.acceptor = Acceptor(self.uid)
        self.learner = Learner(self.uid, self.quorum_size)

    def get_active(self) -> bool:
        return self.active

    def set_active(self, active: bool) -> None:
        self.active = active

    # Proposer methods delegation

    def propose_value(self, value: int) -> None:
        self.proposer.propose_value(value)

    def prepare(self) -> PrepareMessage:
        print("PREPARE: {}".format(self.proposer.proposal_id))
        return self.proposer.prepare()

    def receive_ack_message(self,
                            ack_message: AckMessage
                            ) -> Optional[AcceptMessage]:
        acc_msg = self.proposer.receive_ack_message(ack_message)
        return acc_msg

    # Acceptor methods delegation

    def receive_prepare(self, prepare_message: PrepareMessage) -> AckMessage:
        ack_msg = self.acceptor.receive_prepare(prepare_message)
        return ack_msg

    def receive_accept(self, accept_message: AcceptMessage) \
            -> Optional[AckValueMessage]:
        ack_value = self.acceptor.receive_accept(accept_message)
        return ack_value

    def receive_request(self, value: int) -> Optional[AckValueMessage]:
        ack_value_msg = self.acceptor.receive_request(value)
        return ack_value_msg

    # Learner methods delegation

    def receive_accepted(self, ack_value_msg: AckValueMessage):
        self.learner.receive_accepted(ack_value_msg)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Specify port and number of instances as arguments")
        sys.exit(1)
    port = int(sys.argv[1])
    instances = int(sys.argv[2])
    instance = Instance(str(port), get_fast_quorum_size(instances))
    app.run(debug=True, host='0.0.0.0', port=port)
