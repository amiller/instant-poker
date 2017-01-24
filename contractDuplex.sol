pragma solidity ^0.4.3;

contract SmartDuplex {

    address[2] public players;
    mapping (address => uint) playermap;

    // State, indexed by round
    int bestRound = -1;
    int net;
    uint[2] balances;

    // Can only be incremented by deposit() function
    uint[2] public deposits;

    // Can only be incremented by withdraw() function
    uint[2] withdrawn;

    event LogInit();
    event LogTriggered(uint T1, uint T2);
    event LogNewClaim(int r);
    event LogPlayerOutcome(uint player, string outcome, uint payment);
    event LogOutcome(int round, string outcome);
    event LogPayment(uint player, uint payment);

    uint T1;
    uint T2;

    modifier after_ (uint T) { if (T > 0 && block.number >= T) _; else throw; }
    modifier before(uint T) { if (T == 0 || block.number <  T) _; else throw; }
    modifier onlyplayers { if (playermap[msg.sender] > 0) _; else throw; }
    modifier beforeTrigger { if (T1 == 0) _; else throw; }

    function get_balance() constant returns(uint) {
        return this.balance;
    }

    function latestClaim() constant after_(T1) returns(int) {
        return(bestRound);
    }

    function assert(bool b) internal {
        if (!b) throw;
    }

    function verifySignature(address pub, bytes32 h, uint8 v, bytes32 r, bytes32 s) {
        if (pub != ecrecover(h,v,r,s)) throw;
    }

    function SmartDuplex(address[2] _players) {
        // Assume this channel is funded by the sender
        for (uint i = 0; i < 2; i++) {
            players[i] = _players[i];
            playermap[_players[i]] = (i+1);
        }
        LogInit();
    }
    // Increment on new deposit
    function deposit() onlyplayers beforeTrigger payable {
	deposits[playermap[msg.sender]-1] += msg.value;
    }

    // Increment on withdrawal
    function withdraw() onlyplayers {
	uint i = playermap[msg.sender]-1;
	uint toWithdraw = 0;

	// Before finalizing, can withdraw balance
	if (T2 == 0 || block.number < T2) {
	    toWithdraw = balances[i] - withdrawn[i];
	}

	// After finalizing, can withdraw deposit+net
	else {
	    // positive net: Alice gets money
	    int net2 = (i == 0) ? net : -net;
	    var finalBalance = uint(int(deposits[i]) + net2);
	    toWithdraw = finalBalance - withdrawn[i];
	}
	
	withdrawn[i] = toWithdraw;
	assert(msg.sender.send(toWithdraw));
    }

    // Only when it is time to finalize
    function trigger() onlyplayers beforeTrigger {
        T1 = block.number;
        T2 = block.number + 10;
        LogTriggered(T1, T2);
    }

    function update(uint[3] sig, int r, int _net, uint[2] _balances) onlyplayers before(T2) {
        // Only update to states with larger round number
        if (r <= bestRound) return;
        bestRound = r;

        // Check the signature of the other party
	uint i = (3 - playermap[msg.sender]) - 1;
        var _h = sha3(r, _net, _balances);
	var V =  uint8 (sig[0]);
	var R = bytes32(sig[1]);
	var S = bytes32(sig[2]);
	verifySignature(players[i], _h, V, R, S);

        // Store the new balances
        for (uint j = 0; j < 2; j++) {
            balances[j] = _balances[j];
        }
	net = _net;

        LogNewClaim(r);
    }
}
