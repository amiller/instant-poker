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

def broadcast(p, r, h, sig):
    print 'player[%d]'%p.i, 'broadcasts', r, h.encode('hex'), sig

def broadcastCommitment(p, r, m):
    print 'player[%d]'%p.i, 'opens', r, m.encode('hex')

def sign(h, priv):
    assert len(h) == 32
    pub = bitcoin.privtopub(priv)
    V, R, S = bitcoin.ecdsa_raw_sign(h, priv)
    assert bitcoin.ecdsa_raw_verify(h, (V,R,S), pub)
    return V,R,S

class Player():
    def __init__(self, sk, i, contract):
        self.sk = sk
        self.i = i
        self.contract = contract
        self.n = contract.n_players()
        self.lastClosedRound = -1
        self.lastOpenRound = -1
        self.hashes = [zfill('')] * self.n
        self.isTriggered = False
        self.lastRound = None
        self.secondLastRound = None

    def subprotocolOutput(self, r, hashes, m):
        assert not self.isTriggered
        assert len(hashes) == self.n
        assert r == self.lastOpenRound + 1
        assert self.lastOpenRound == self.lastClosedRound
        assert hashes[self.i] == utils.sha3(m)
        self.hashes = hashes
        self.h = utils.sha3(zfill(utils.int_to_bytes(r)) + ''.join(hashes))
        self.m = m
        sig = sign(self.h, self.sk)
        broadcast(self, r, self.h, sig)
        self.lastOpenRound += 1
        self.sigs = None # We don't have signatures for the open round yet
        return sig

    def receiveSignatures(self, r, sigs):
        assert not self.isTriggered
        assert r == self.lastOpenRound == self.lastClosedRound + 1
        # Signatures received, we can broadcast our share
        # TODO: check each signature
        self.sigs = sigs
        broadcastCommitment(self, r, self.m)
        return self.m

    def receiveOpenings(self, r, openings):
        assert not self.isTriggered
        assert r == self.lastOpenRound == self.lastClosedRound + 1
        assert self.sigs is not None
        self.lastClosedRound += 1
        self.secondLastRound = self.lastRound;
        self.lastRound = (self.sigs, self.hashes, self.h, self.m, openings)

    def respondT1(self):
        # It's time to submit our evidence
        assert not self.isTriggered
        self.isTriggered = True

        if self.lastRound is None:
            # TODO: what to do here?
            return

        g = s.block.gas_used
        if self.lastOpenRound > self.lastClosedRound and self.sigs:
            # Claim the current open round (we have sigs for it)
            print 'last open round:', self.lastOpenRound
            self.contract.submitClaim(flatten(self.sigs), self.lastOpenRound,
                                      self.hashes, sender=self.sk)

        # At minimum, submit the last closed round
        (sigs, hashes, h, m, openings) = self.lastRound
        sigs = flatten(sigs)
        print 'last closed:', self.lastClosedRound
        self.contract.submitClaim(sigs, self.lastClosedRound,
                                  hashes, sender=self.sk)
        print 'respondT1:', s.block.gas_used - g        

    def respondT2(self):
        # To be called immediately after time T1
        latestClaim = self.contract.latestClaim()
        print dict(latestClaim=latestClaim,open=self.lastOpenRound,closed=self.lastClosedRound)

        assert latestClaim in (self.lastOpenRound, self.lastClosedRound)
        g = s.block.gas_used                    
        
        if latestClaim == self.lastOpenRound:
            # Reveal the current message, we may not get the final output,
            # but if not, at least we will get COMPENSATION
            contract.openCommitment(self.m)

        # Reveal the last round message, which we already have output for
        (_, hashes, _, m, openings) = self.lastRound
        contract.openCommitment(m)
        for (opening, h) in zip(openings, hashes):
            # We will have to sort this round
            assert h == utils.sha3(opening)
            contract.openCommitment(opening)

        print 'respondT2:', s.block.gas_used - g

    def readLastRound(self):
        # This is only useful after the contract has been triggered
        if self.lastOpenRound < self.lastClosedRound:
            if self.contract.deadlinePassed():
                print "Output isn't ready yet"
            elif self.contract.getFinalValue():
                print "Output available"
            else:
                print "Output wasn't available, but we have received a penalty"


# Create the simulated blockchain
s = tester.state()
s.mine()
tester.gas_limit = 3141592

# Create the contract
contract_code = open('contractSmartAmortizePayments.sol').read()
contract = s.abi_contract(contract_code, language='solidity')

keys = [tester.k1,
        tester.k2,
        tester.k3,
        tester.k4]
addrs = map(utils.privtoaddr, keys)


# The +100 here is for the balance
contract.initialize(addrs, value=1000*(len(keys)-1)*len(keys) + 100)
print 'players:', contract.n_players();


def shares_of_message(m, n):
    import os
    shares = [os.urandom(32) for _ in range(n)]
    shares[-1] = reduce(xors, shares[:-1], m)
    return shares

def partialRound(players, round, shares):
    hashes = map(utils.sha3, shares)    
    print 'Opening the round for each player'
    sigs = []
    for shr,p in zip(shares,players):
        assert round == p.lastOpenRound + 1
        sigs.append(p.subprotocolOutput(round, hashes, shr))
    return sigs

def completeRound(players, round, shares):
    hashes = map(utils.sha3, shares)
    sigs = partialRound(players, round, shares)

    print 'Distributing signatures'
    for p in players:
        p.receiveSignatures(round, sigs)
        p.receiveOpenings(round, shares)

# Play a few rounds
def encode_balance(balances):
    assert len(balances) <= 32
    assert sum(balances) <= 100
    assert all(0 <= b < 256 for b in balances)
    val = 0
    for b in balances[::-1]:
        val *= 256;
        val += b;
    return zfill(utils.int_to_bytes(val))

# Take a snapshot before trying out test cases
#try: s.revert(s.snapshot())
#except: pass # FIXME: I HAVE NO IDEA WHY THIS IS REQUIRED
s.mine()
base = s.snapshot()

def test_OK():
    #s.revert(base)  # Restore the snapshot
    players = [Player(sk, i, contract) for i,sk in enumerate(keys)]

    for round in range(3):
        # Pick some arbitrary payment distribution, summing to 100
        shares = shares_of_message(encode_balance([10,4,86]), len(players))
        completeRound(players, round, shares)

    # Anyone can trigger a recovery
    print 'Triggering'
    contract.trigger(sender=keys[0])

    # Allow everyone to respond to the trigger
    for p in players:
        print 'player[%d]' % p.i, 'responding to T1'
        p.respondT1()

    #s.mine(15)

    # Allow everyone to respond to the claim deadline
    for p in players:
        print 'player[%d]' % p.i, 'responding to T2'
        p.respondT2()
        
    s.mine(25);
    # Anyone can finalize
    g = s.block.gas_used
    contract.finalize()
    print 'Finalize:', s.block.gas_used - g

def test_1Bad():
    #s.revert(base)  # Restore the snapshot
    players = [Player(sk, i, contract) for i,sk in enumerate(keys)]

    for round in range(3):
        # Pick some arbitrary payment distribution, summing to 100
        shares = shares_of_message(encode_balance([10,4,86]), len(players))
        completeRound(players, round, shares)

    # One player receives all the signatures for a higher round
    shares = shares_of_message(encode_balance([10,4,86]), len(players))
    sigs = partialRound(players, 3, shares)
    players[0].receiveSignatures(3, sigs)

    # Anyone can trigger a recovery
    print 'Triggering'
    contract.trigger(sender=keys[0])

    # Player 0 crashes
    # Allow everyone else to respond to the trigger
    for p in players[:-2]:
        print 'player[%d]' % p.i, 'responding to T1'
        p.respondT1()

    s.mine(10);

    # Allow everyone to respond to the claim deadline
    for p in players[:-2]:
        print 'player[%d]' % p.i, 'responding to T2'
        p.respondT2()
        
    s.mine(15);
    # Anyone can finalize
    g = s.block.gas_used
    contract.finalize()
    print 'Finalize:', s.block.gas_used - g


