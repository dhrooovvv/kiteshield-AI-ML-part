// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @notice Sepolia-only guarded session vault. Owner authority is separate from the agent.
contract GuardedVault {
    address public immutable owner;
    address public agent;
    address payable public recipient;
    uint256 public remaining;
    uint256 public perPayment;
    uint256 public expires;
    uint256 public nonce;
    uint256 public epoch;
    bool public paused;
    bool private entered;

    event Deposit(address indexed from, uint256 amount);
    event SessionConfigured(uint256 epoch);
    event Paid(address indexed recipient, uint256 amount, uint256 nonce);
    event Paused();
    event Recovered(uint256 amount, uint256 epoch);

    modifier onlyOwner() { require(msg.sender == owner, "OWNER_ONLY"); _; }
    modifier onlyAgent() { require(msg.sender == agent, "AGENT_ONLY"); _; }

    constructor(address owner_) {
        require(block.chainid == 11155111, "SEPOLIA_ONLY");
        require(owner_ != address(0), "ZERO_OWNER");
        owner = owner_;
    }

    function configure(address agent_, address payable recipient_, uint256 budget,
                       uint256 perPayment_, uint256 expires_) external onlyOwner {
        require(agent_ != address(0) && agent_ != owner, "DISTINCT_AGENT");
        require(recipient_ != address(0), "ZERO_RECIPIENT");
        require(budget > 0 && perPayment_ > 0 && perPayment_ <= budget, "BUDGET");
        require(expires_ > block.timestamp && expires_ <= block.timestamp + 1 days, "EXPIRY");
        agent = agent_;
        recipient = recipient_;
        remaining = budget;
        perPayment = perPayment_;
        expires = expires_;
        epoch++;
        // Configuration does not silently resume a self-quarantined agent.
        emit SessionConfigured(epoch);
    }

    function tighten(uint256 budget, uint256 perPayment_, uint256 expires_) external onlyAgent {
        require(budget <= remaining && perPayment_ <= perPayment && expires_ <= expires, "TIGHTEN_ONLY");
        remaining = budget;
        perPayment = perPayment_;
        expires = expires_;
    }

    function pause() external {
        require(msg.sender == agent || msg.sender == owner, "NOT_AUTHORIZED");
        paused = true;
        emit Paused();
    }

    function resume() external onlyOwner { paused = false; }

    function recover(uint256 amount) external onlyOwner {
        require(!entered && amount > 0 && amount <= address(this).balance, "RECOVERY");
        entered = true;
        paused = true;
        uint256 afterBalance = address(this).balance - amount;
        if (remaining > afterBalance) remaining = afterBalance;
        epoch++;
        (bool ok,) = payable(owner).call{value: amount}("");
        require(ok, "TRANSFER_FAILED");
        entered = false;
        emit Recovered(amount, epoch);
    }

    function pay(uint256 amount, uint256 expectedNonce, uint256 expectedEpoch) external onlyAgent {
        require(!entered && !paused, "PAUSED_OR_REENTRANT");
        require(block.timestamp < expires, "EXPIRED");
        require(expectedNonce == nonce && expectedEpoch == epoch, "STALE_ACTION");
        require(amount > 0 && amount <= perPayment && amount <= remaining, "BUDGET");
        entered = true;
        remaining -= amount;
        nonce++;
        (bool ok,) = recipient.call{value: amount}("");
        require(ok, "TRANSFER_FAILED");
        entered = false;
        emit Paid(recipient, amount, expectedNonce);
    }

    receive() external payable { emit Deposit(msg.sender, msg.value); }
}
