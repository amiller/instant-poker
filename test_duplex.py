from ethereum import tester
from ethereum import utils
from ethereum._solidity import get_solidity
SOLIDITY_AVAILABLE = get_solidity() is not None

import bitcoin

# Logging
from ethereum import slogging
slogging.configure(':INFO,eth.vm:INFO')
#slogging.configure(':DEBUG')
#slogging.configure(':DEBUG,eth.vm:TRACE')

xor = lambda (x,y): chr(ord(x) ^ ord(y))
xors = lambda x,y: ''.join(map(xor,zip(x,y)))
zfill = lambda s: (32-len(s))*'\x00' + s
flatten = lambda x: [z for y in x for z in y]

def coerce_uint256(x):
    return x % 2**256

def sign(h, priv):
    assert len(h) == 32
    pub = bitcoin.privtopub(priv)
    V, R, S = bitcoin.ecdsa_raw_sign(h, priv)
    assert bitcoin.ecdsa_raw_verify(h, (V,R,S), pub)
    return V,R,S

def broadcast(p, r, h, sig):
    print 'player[%d]'%p.i, 'broadcasts', r, h.encode('hex'), sig

class Player():
    def __init__(self, sk, i, contract):
        self.sk = sk
        self.i = i
        self.contract = contract
        self.n = 2

        # Invariants:
        # - balances[i] is monotonic
        # - balances[i] - net[i] <= deposit[i]

        # deposits = [0,0]
        self.net = 0
        self.balances = [0,0]

        
        self.isTriggered = False
        self.lastClosedRound = -1
        self.lastOpenRound = -1
        self.lastRound = None

    # Assumption: parties must agree on the new balance/net out of band
    def subprotocolOutput(self, r, net, balances):
        assert not self.isTriggered
        assert len(balances) == self.n

        # Sanity checks
        assert all(b >= 0 for b in balances)       # Non-negative balances
        assert r == self.lastOpenRound + 1         # Only go forward
        assert self.lastOpenRound == self.lastClosedRound

        # 1) Do not let parties withdraw (or pay) more than they have deposited
        net2 = [self.net, -self.net]
        deposits = [contract.deposits(0), contract.deposits(1)]
        assert balances[0] - net2[0] <= deposits[0]
        assert balances[1] - net2[1] <= deposits[1]

        # 2) Balances only go forward
        if self.lastClosedRound >= 0:
            assert balances[0] >= self.lastRound[2][0]
            assert balances[1] >= self.lastRound[2][1]

        # Sign the new balance update
        self.lastOpenRound += 1
        self.balances = balances
        self.net = net
        self.h = utils.sha3(zfill(utils.int_to_bytes(r)) + ''.join(zfill(utils.int_to_bytes(b)) for b in [coerce_uint256(net)] + balances))
        sig = sign(self.h, self.sk)
        broadcast(self, r, self.h, sig)
        return sig
        
    def receiveSignatures(self, r, sigs):
        assert not self.isTriggered
        assert r == self.lastOpenRound == self.lastClosedRound + 1
        # Signatures received, we can broadcast our share
        for i,(V,R,S) in enumerate(sigs):
            pub = contract.players(i).decode('hex')
            # TODO: verify signature
            ##assert bitcoin.ecdsa_raw_recover(self.h, (V,R,S)) == pub

        self.sigs = sigs
        self.lastClosedRound += 1
        self.lastRound = (self.sigs, self.net, self.balances)

    def submitLatest(self):
        (sigs, net, balances) = self.lastRound
        sigs = flatten(sigs)
        # Duplex tweak: ignore our own signature
        if self.i == 0: sigs = sigs[3:]
        else:           sigs = sigs[:3]
            
        print 'last closed:', self.lastClosedRound
        g = s.block.gas_used
        self.contract.update(sigs, self.lastClosedRound,
                                  net, balances, sender=self.sk)
        print 'contract.update():', s.block.gas_used - g

    def withdraw(self):
        self.contract.withdraw(sender=self.sk)

    def respondT1(self):
        # It's time to submit our evidence
        assert not self.isTriggered
        self.isTriggered = True
        self.submitLatest()


# Create the simulated blockchain
s = tester.state()
s.mine()
tester.gas_limit = 3141592


# Two players
keys = [tester.k1,
        tester.k2]
addrs = map(utils.privtoaddr, keys)

# Create the contract
contract_code = open('contractDuplex.sol').read()
contract = s.abi_contract(contract_code,
                          language='solidity',
                          constructor_parameters=(addrs,))

#contract.initialize(, value=1000, sender=keys[0])
print 'players:', contract.players(0), contract.players(1)
contract.deposit(value=50, sender=keys[0])
contract.deposit(value=50, sender=keys[1])

def partialRound(players, round, net, balances):
    print 'Opening the round for each player'
    sigs = []
    for p in players:
        assert round == p.lastOpenRound + 1
        sigs.append(p.subprotocolOutput(round, net, balances))
    return sigs

def completeRound(players, round, net, balances):
    sigs = partialRound(players, round, net, balances)

    print 'Distributing signatures'
    for p in players:
        p.receiveSignatures(round, sigs)

# Take a snapshot before trying out test cases
#try: s.revert(s.snapshot())
#except: pass # FIXME: I HAVE NO IDEA WHY THIS IS REQUIRED
s.mine()
base = s.snapshot()

def test_OK():
    #s.revert(base)  # Restore the snapshot
    global players
    players = [Player(sk, i, contract) for i,sk in enumerate(keys)]

    # Step 1: Alice pays Bob 10, withdraws 20
    completeRound(players, 0, -10, [20, 0])

    # Step 2: Bob withdraws 60
    completeRound(players, 1, -10, [20,60])

    players[1].submitLatest()
    players[1].withdraw()

    # Step 3: Alice withdraws remaining 20
    completeRound(players, 2, -10, [40,60])

    contract.trigger(sender=keys[0])
    
    for p in players:
        p.respondT1()

    s.mine(10)
    
    contract.withdraw(sender=keys[0])
    contract.withdraw(sender=keys[1])
