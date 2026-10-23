import pytest

from war_room.gate import Gate
from war_room.planner import Step

ASK = "Send seller 40218 a WhatsApp saying their October payout is under review."


def send(seller_id=40218, message="Your October payout is under review.", origin="user"):
    return Step("send_seller_whatsapp", {"seller_id": seller_id, "message": message}, "send", "send", origin=origin)


@pytest.fixture
def gate():
    return Gate([40107, 40218])


def test_user_request_is_allowed(gate):
    assert gate.check(send(), ASK) == (True, "ok")


@pytest.mark.parametrize("step, question, why", [
    (send(origin="doc:note-seller-40218"), ASK, "not by the user"),
    (send(), "Summarise the open tickets for seller 40218.", "did not ask"),
    (send(seller_id=40299), "Send seller 40299 a WhatsApp saying hi.", "allow-list"),
    (send(seller_id="all"), "Send every seller a WhatsApp saying hi.", "allow-list"),
    (send(seller_id=40107), ASK, "not named"),
    (send(message="Rs 5000 credited, details at https://bb.example/pay"), ASK, "links"),
    (send(message="We have approved a ₹5,000 credit for you."), ASK, "money"),
    (send(message=""), ASK, "characters"),
])
def test_gate_refuses(gate, step, question, why):
    allowed, reason = gate.check(step, question)
    assert not allowed and why in reason
