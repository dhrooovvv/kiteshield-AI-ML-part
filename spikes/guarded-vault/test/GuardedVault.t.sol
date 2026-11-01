// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {GuardedVault} from "../src/GuardedVault.sol";

interface Vm {
    function addr(uint256) external returns(address);
    function deal(address,uint256) external;
    function prank(address) external;
    function expectRevert() external;
    function warp(uint256) external;
    function chainId(uint256) external;
}

contract GuardedVaultTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    GuardedVault vault;
    address owner;
    address agent;
    address payable supplier = payable(address(0xBEEF));
    function setUp() public {
        vm.chainId(11155111);
        owner = vm.addr(0x111); // separate test-only owner key
        agent = vm.addr(0x222); // separate test-only agent key
        vault = new GuardedVault(owner);
        vm.deal(address(vault), 10 ether);
        vm.prank(owner);
        vault.configure(agent, supplier, 2 ether, 1 ether, block.timestamp + 1 hours);
    }
    function testAgentPaysWithinBudget() public {
        vm.prank(agent); vault.pay(1 ether, 0, 1);
        require(supplier.balance == 1 ether && vault.remaining() == 1 ether);
    }
    function testAgentCannotExpandOrConfigure() public {
        vm.expectRevert(); vm.prank(agent);
        vault.configure(agent, supplier, 9 ether, 9 ether, block.timestamp + 1 hours);
        vm.expectRevert(); vm.prank(agent);
        vault.tighten(3 ether, 1 ether, block.timestamp + 1 hours);
    }
    function testAgentCanTighten() public {
        vm.prank(agent); vault.tighten(1 ether, 0.5 ether, block.timestamp + 10 minutes);
        vm.expectRevert(); vm.prank(agent); vault.pay(0.6 ether, 0, 1);
        vm.prank(agent); vault.pay(0.5 ether, 0, 1);
        require(vault.remaining() == 0.5 ether);
    }
    function testReplayAndStaleEpochFail() public {
        vm.prank(agent); vault.pay(1 ether, 0, 1);
        vm.expectRevert(); vm.prank(agent); vault.pay(1 ether, 0, 1);
        vm.expectRevert(); vm.prank(agent); vault.pay(1 ether, 1, 0);
    }
    function testOnlyOwnerResumesQuarantine() public {
        vm.prank(agent); vault.pause();
        vm.expectRevert(); vm.prank(agent); vault.resume();
        vm.expectRevert(); vm.prank(agent); vault.pay(1 ether, 0, 1);
        vm.prank(owner); vault.resume();
        vm.prank(agent); vault.pay(1 ether, 0, 1);
    }
    function testDepositNeverExpandsBudget() public {
        vm.deal(address(this), 1 ether);
        (bool ok,) = address(vault).call{value: 1 ether}("");
        require(ok && vault.remaining() == 2 ether);
    }
    function testExpiredAndUnauthorizedPaymentsFail() public {
        vm.expectRevert(); vault.pay(1 ether, 0, 1);
        vm.warp(block.timestamp + 1 hours);
        vm.expectRevert(); vm.prank(agent); vault.pay(1 ether, 0, 1);
    }
    function testFuzzCap(uint96 amount) public {
        if (amount == 0 || amount > 1 ether) {
            vm.expectRevert(); vm.prank(agent); vault.pay(amount, 0, 1);
        } else {
            vm.prank(agent); vault.pay(amount, 0, 1);
            require(vault.remaining() == 2 ether - amount);
        }
    }
    function testRejectWrongChain() public {
        vm.chainId(1);
        vm.expectRevert(); new GuardedVault(owner);
    }
}
