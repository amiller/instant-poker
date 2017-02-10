pragma solidity ^0.4.3;

contract SmartAmortize {

    uint constant COMPENSATION = uint(1000);
    bytes32 constant INITIAL_STATE = 0x000000000000000000000000000000000000000000000000000000000056040a;

    address[] public players;
    int256 bestRound = -1;
    int256 secondBestRound = -1;
    mapping(int => bytes32[]) commits;

    mapping (address => uint) playermap;
    mapping (bytes32 => bytes32) openings;

    event LogInit(uint256 n_players);
    event LogTriggered(uint256 T1, uint256 T2);
    event LogNewClaim(int r);
    event LogPlayerOutcome(uint256 player, string outcome, uint payment);
    event LogOutcome(int256 round, string outcome);
    event LogPayment(uint256 player, uint payment);

    uint256 T1;
    uint256 T2;
    uint256 T3;

    modifier after_ (uint T) { if (T > 0 && block.number >= T) _; else throw; }
    modifier before(uint T) { if (T > 0 && block.number <  T) _; else throw; }
    modifier onlyplayers { if (playermap[msg.sender] > 0) _; else throw; }
    modifier beforeInit { if (players.length == 0) _; else throw; }
    modifier afterInit { if (players.length > 0) _; else throw; }
    modifier beforeTrigger { if (T1 == 0) _; else throw; }

    function n_players() constant returns(uint) {
	return players.length;
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
    
    function initialize(address[] _players) beforeInit payable {
	// All of the collateral must be deposited on initialiazation
	assert(this.balance >= COMPENSATION * (_players.length - 1) * _players.length + 100);
        for (uint i = 0; i < _players.length; i++) {
	    players.push(_players[i]);
	    playermap[_players[i]] = (i+1);
	}
	LogInit(_players.length);
    }

    function trigger() onlyplayers afterInit beforeTrigger {
	T1 = block.number;
	T2 = block.number + 10;
	T3 = block.number + 20;
	LogTriggered(T1, T2);
    }

    function submitClaim(uint[] sigs, int r, bytes32[] _commits)
    after_(T1) before(T2) {
	var _h = sha3(r, _commits);
	assert(sigs.length == 3 * players.length);

	// Check all the signatures, store all the new commitments
	commits[r] = new bytes32[](players.length);
	for (uint j = 0; j < players.length; j++) {
	    var V = uint8(sigs[3*j]);
	    var R = bytes32(sigs[3*j+1]);
	    var S = bytes32(sigs[3*j+2]);
	    verifySignature(players[j], _h, V, R, S);
	    commits[r][j] = _commits[j];
	}

	// Advance to a new claim with a larger number
	if (r > bestRound) {
	    secondBestRound = bestRound;
	    bestRound = r;
	} else if (r > secondBestRound) {
	    secondBestRound = r;
	}
	LogNewClaim(r);
    }

    function openCommitment(bytes32 opening) {
	var commit = sha3(opening);
	openings[commit] = opening;
    }

    function determineOutput(bytes32 value) internal returns(uint[]) {
	// Determine the payout to parties as a function of the value.
	// This is an application specific function.
	// One interpretation may be to treat the value as a hash
	// or a merkle root of account balances, in which case we would
	// have to load the values ahead of time or pass them as aux data.

	// This example assumes that the payment to each player is represented
	// by one byte
	assert(players.length <= 32);
	uint256 val = uint256(value);
	uint[] memory payments = new uint[](players.length);
	for (var i = 0; i < players.length; i++) {
	    uint8 v = uint8(val & 255);
	    payments[i] = v;
	    val /= 256;
	}
	return payments;
    }

    function finalize() after_(T3) {
	uint DEPOSIT = COMPENSATION * (players.length - 1);
	uint[] memory PAYMENT;
	
	// Issue the payouts
	var anyCorrupt = false;
	for (var i = 0; i < players.length; i++) {
	    // Did any player fail?
	    if (openings[commits[bestRound][i]] == 0)
		anyCorrupt = true;
	}

	// What is the payment?
	bytes32 state = 0;
	if (!anyCorrupt) {
	    // No corruptions.
	    // We can reconstruct the value from the current round
	    for (i = 0; i < players.length; i++) {
		state ^= openings[commits[bestRound][i]];
	    }
	    PAYMENT = determineOutput(state);
	    LogOutcome(bestRound, "bestRound");
	} else if (secondBestRound >= 0) {
	    // If the current round aborts, we will instead pay out according
	    // to the *second* best round. This can only fail if there are 0 honest
	    // parties, in which case the outcome does not matter.
	    for (i = 0; i < players.length; i++) {
		state ^= openings[commits[secondBestRound][i]];
	    }
	    PAYMENT = determineOutput(state);
	    LogOutcome(secondBestRound, "secondBestRound");
	} else {
	    state = INITIAL_STATE;
	    PAYMENT = determineOutput(state);
	    LogOutcome(secondBestRound, "initialState");
	}

	for (i = 0; i < players.length; i++) {
	    if (openings[commits[bestRound][i]] != 0) {
		if (anyCorrupt) {
		    // This player is OK, they responded to the latest claim
		    assert(players[i].send(DEPOSIT + COMPENSATION + PAYMENT[i]));
		    LogPlayerOutcome(i, "deposit + compensation + payment", PAYMENT[i]);
		} else {
		    // Everyone receives deposit
		    assert(players[i].send(DEPOSIT + PAYMENT[i]));
		    LogPlayerOutcome(i, "deposit + payment", PAYMENT[i]);
		}
	    } else {
		// Punish this player!
		LogPlayerOutcome(i, "bad", 0);
	    }
	}
    }
}
