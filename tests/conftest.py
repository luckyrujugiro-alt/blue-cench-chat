import asyncio
import os
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from bluecenchchat.backend.authentication import AuthService, RegistrationData  # noqa: E402
from bluecenchchat.backend.database import Database  # noqa: E402
from bluecenchchat.core.node import BlueCenchChatNode  # noqa: E402


def make_account(db, name):
    auth = AuthService(db)
    data = RegistrationData(full_name=f"{name.title()} Tester", username=name, email=f"{name}@example.com",
                            password="Passw0rd!x", confirm_password="Passw0rd!x")
    acc, rk, ident = auth.register(data)
    return acc, rk, ident


async def wait_for(pred, timeout=10.0, step=0.02):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if pred():
            return True
        await asyncio.sleep(step)
    raise AssertionError("condition not met in time")


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("BLUECENCHCHAT_HOME", str(tmp_path / "home"))
    return tmp_path


@pytest.fixture
async def pair(tmp_path):
    """Two independent Blue Cench Chat nodes (separate databases) on real sockets."""
    port = random.randint(48000, 60000)
    nodes = []
    for name in ("alice", "bob"):
        db = Database(tmp_path / f"{name}.db")
        acc, _, ident = make_account(db, name)
        node = BlueCenchChatNode(db, acc.id, ident, beacon_port=port)
        dl = tmp_path / f"{name}_downloads"
        dl.mkdir()
        node.update_settings(download_dir=str(dl))
        await node.start()
        nodes.append(node)
    yield nodes
    for n in nodes:
        await n.stop()


async def connect_and_accept(a, b):
    cid_b_on_a = await a.connections.connect(lan=("127.0.0.1", b.lan.port))
    await a.connections.send_request(cid_b_on_a, "hi")
    await wait_for(lambda: b.repo.contact_by_peer(a.identity.user_id) is not None
                   and b.repo.contact_by_peer(a.identity.user_id).status == "pending_in")
    cid_a_on_b = b.repo.contact_by_peer(a.identity.user_id).id
    await b.connections.accept(cid_a_on_b)
    await wait_for(lambda: a.repo.contact(cid_b_on_a).status == "accepted")
    return cid_b_on_a, cid_a_on_b
