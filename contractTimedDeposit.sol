pragma solidity ^0.4.3;

contract PrepareDeposits {
    modifier after_ (uint T) { if (T > 0 && block.number >= T) _; else throw; }
    modifier before(uint T) { if (T == 0 || block.number <  T) _; else throw; }    
    
    uint T1;
    uint threshold;
    address recipient;
    
    bool complete;
    mapping (address => uint) deposits;
    
    function PrepareDeposits(uint _T1, uint _threshold, address _recipient) {
	T1 = _T1;
	threshold = _threshold;
	recipient = _recipient;
    }

    function finalize() after_(T1) {
	if (complete) recipient.send(this.balance);
    }

    function withdraw() after_(T1) {
	if (!complete) {
	    msg.sender.send(deposits[msg.sender]);
	    deposits[msg.sender] = 0;
	}
    }

    function deposit() before(T1) payable {
	deposits[msg.sender] += msg.value;
	if (this.balance >= threshold) complete = true;
    }
}	 
