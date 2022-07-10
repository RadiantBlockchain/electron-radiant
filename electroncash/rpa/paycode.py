#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# -*- mode: python3 -*-
# This file (c) 2020 Jonald Fyookball
# With tweaks from Calin Culianu
# Part of the Electron Cash SPV Wallet
# License: MIT

'''
This implements the functionality for RPA (Reusable Payment Address) aka Paycodes
'''

from decimal import Decimal as PyDecimal
import time

from . import addr
from .. import bitcoin
from .. import transaction
from ..address import Address, Base58
from ..bitcoin import *  # COIN, TYPE_ADDRESS, sha256
from ..plugins import run_hook
from ..transaction import Transaction, OPReturn
from ..keystore import KeyStore
from ..util import print_msg
from .. import networks


def _satoshis(amount):
    # satoshi conversion must not be performed by the parser
    return int(COIN * PyDecimal(amount)
               ) if amount not in ['!', None] else amount


def _resolver(wallet, x, nocheck):
    if x is None:
        return None
    out = wallet.contacts.resolve(x)
    if out.get('type') == 'openalias' and nocheck is False and out.get(
            'validated') is False:
        raise BaseException('cannot verify alias', x)
    return out['address']


def _mktx(wallet, config, outputs, fee=None, change_addr=None, domain=None, nocheck=False,
          unsigned=False, password=None, locktime=None, op_return=None, op_return_raw=None):
    if op_return and op_return_raw:
        raise ValueError(
            'Both op_return and op_return_raw cannot be specified together!')

    domain = None if domain is None else map(
        lambda x: _resolver(wallet, x, nocheck), domain)
    final_outputs = []
    if op_return:
        final_outputs.append(OPReturn.output_for_stringdata(op_return))
    elif op_return_raw:
        try:
            op_return_raw = op_return_raw.strip()
            tmp = bytes.fromhex(op_return_raw).hex()
            assert tmp == op_return_raw.lower()
            op_return_raw = tmp
        except Exception as e:
            raise ValueError(
                "op_return_raw must be an even number of hex digits") from e
        final_outputs.append(OPReturn.output_for_rawhex(op_return_raw))

    for address, amount in outputs:
        address = _resolver(wallet, address, nocheck)
        amount = _satoshis(amount)
        final_outputs.append((TYPE_ADDRESS, address, amount))

    coins = wallet.get_spendable_coins(domain, config)
    try:
        tx = wallet.make_unsigned_transaction(
            coins, final_outputs, config, fee, change_addr)
    except BaseException:
        return 0
    if locktime is not None:
        tx.locktime = locktime
    if not unsigned:
        run_hook('sign_tx', wallet, tx)
        wallet.sign_transaction(tx, password)
    return tx


def _calculate_paycode_shared_secret(private_key, public_key, outpoint):
    """private key is expected to be an integer.
    public_key is expected to be bytes.
    outpoint is expected to be a string.
    returns the paycode shared secret as bytes"""

    from ..bitcoin import Point
    from ..bitcoin import curve_secp256k1 as curve

    # Public key is expected to be compressed.  Change into a point object.
    pubkey_point = bitcoin.ser_to_point(public_key)
    ecdsa_point = Point(curve, pubkey_point.x(), pubkey_point.y())

    # Multiply the public and private points together
    ecdh_product = ecdsa_point * private_key
    ecdh_x = int(ecdh_product.x())
    ecdh_x_bytes = ecdh_x.to_bytes(33, byteorder="big")

    # Get the hash of the product
    sha_ecdh_x_bytes = sha256(ecdh_x_bytes)
    sha_ecdh_x_as_int = int.from_bytes(sha_ecdh_x_bytes, byteorder="big")

    # Hash the outpoint string
    hash_of_outpoint = sha256(outpoint)
    hash_of_outpoint_as_int = int.from_bytes(hash_of_outpoint, byteorder="big")

    # Sum the ECDH hash and the outpoint Hash
    grand_sum = sha_ecdh_x_as_int + hash_of_outpoint_as_int

    # Hash the final result
    nbytes = (len("%x" % grand_sum) + 1) // 2
    grand_sum_bytes = grand_sum.to_bytes(nbytes, byteorder="big")
    shared_secret = sha256(grand_sum_bytes)

    return shared_secret


def _generate_address_from_pubkey_and_secret(parent_pubkey, secret):
    """parent_pubkey and secret are expected to be bytes
    This function generates a receiving address based on CKD."""

    new_pubkey = bitcoin.CKD_pub(parent_pubkey, secret, 0)[0]
    use_uncompressed = True

    # Currently, just uses compressed keys, but if this ever changes to
    # require uncompressed points:
    if use_uncompressed:
        pubkey_point = bitcoin.ser_to_point(new_pubkey)
        x_coord = hex(pubkey_point.x())[2:].zfill(64)
        y_coord = hex(pubkey_point.y())[2:].zfill(64)
        uncompressed = "04" + \
            hex(pubkey_point.x())[2:].zfill(64) + \
            hex(pubkey_point.y())[2:].zfill(64)
        new_pubkey = bytes.fromhex(uncompressed)
    return Address.from_pubkey(new_pubkey)


def _generate_privkey_from_secret(parent_privkey, secret):
    """parent_privkey and secret are expected to be bytes
    This function generates a receiving address based on CKD."""

    return bitcoin.CKD_priv(parent_privkey, secret, 0)[0].hex()


def get_grind_string(wallet, prefix_size="10"):

    if prefix_size == "04":
        prefix_chars = 1
    elif prefix_size == "08":
        prefix_chars = 2
    elif prefix_size == "0C":
        prefix_chars = 3
    elif prefix_size == "10":
        prefix_chars = 4
    else:
        raise ValueError("Invalid prefix size. Must be 4,8,12, or 16 bits.")

    scanpubkey = wallet.derive_pubkeys(0, 0)
    grind_string = scanpubkey[2:prefix_chars + 2].upper()
    return grind_string


def generate_paycode(wallet, prefix_size="10"):
    """prefix size should be either 0x04 , 0x08, 0x0C, 0x10"""

    # Fields of the paycode
    version = "01"
    if networks.net.TESTNET:
        version = "05"
    scanpubkey = wallet.derive_pubkeys(0, 0)
    spendpubkey = wallet.derive_pubkeys(0, 1)
    expiry = "00000000"

    # Concatenate
    payloadstring = version + prefix_size + scanpubkey + spendpubkey + expiry

    # Convert to bytes
    payloadbytes = bytes.fromhex(payloadstring)

    # Generate paycode "address" via rpa.addr function
    prefix = networks.net.RPA_PREFIX
    return addr.encode_full(prefix, addr.PUBKEY_TYPE, payloadbytes)


def generate_transaction_from_paycode(wallet, config, amount, rpa_paycode=None, fee=None, from_addr=None,
                                      change_addr=None, nocheck=False, unsigned=False, password=None, locktime=None,
                                      op_return=None, op_return_raw=None, progress_callback=None, exit_event=None):
    if not wallet.is_schnorr_enabled():
        print_msg(
            "You must enable schnorr signing on this wallet for RPA.  Exiting.")
        return 0

    # Decode the paycode
    rprefix, addr_hash = addr.decode(rpa_paycode)
    paycode_hex = addr_hash.hex().upper()

    # Parse paycode
    paycode_field_version = paycode_hex[0:2]
    paycode_field_prefix_size = paycode_hex[2:4]
    paycode_field_scan_pubkey = paycode_hex[4:70]
    paycode_field_spend_pubkey = paycode_hex[70:136]
    paycode_field_expiry = paycode_hex[136:144]
    paycode_field_checksum = paycode_hex[144: 154]

    paycode_expiry = int.from_bytes(bytes.fromhex(paycode_field_expiry), byteorder='big', signed=False)
    if paycode_expiry != 0:
        one_week_from_now = int(time.time()) + 604800
        if paycode_expiry < one_week_from_now:
            raise BaseException('Paycode expired.')

    # Initialize a few variables for the transaction
    tx_fee = _satoshis(fee)
    domain = from_addr.split(',') if from_addr else None

    # Initiliaze a few variables for grinding
    tx_matches_paycode_prefix = False
    grind_nonce = 0
    grinding_version = "1"

    if paycode_field_prefix_size == "04":
        prefix_chars = 1
    elif paycode_field_prefix_size == "08":
        prefix_chars = 2
    elif paycode_field_prefix_size == "0C":
        prefix_chars = 3
    elif paycode_field_prefix_size == "10":
        prefix_chars = 4
    else:
        raise ValueError("Invalid prefix size. Must be 4,8,12, or 16 bits.")

    # Construct the transaction, initially with a dummy destination
    rpa_dummy_address = wallet.dummy_address().to_string(Address.FMT_CASHADDR)
    unsigned = True
    tx = _mktx(wallet, config, [(rpa_dummy_address, amount)], tx_fee, change_addr, domain, nocheck, unsigned,
               password, locktime, op_return, op_return_raw)

    # HANDLE A FAILURE BY RETURNING ZERO (FOR NOW)
    if tx == 0:
        return 0

    # Use the first input (input zero) for our shared secret
    input_zero = tx._inputs[0]

    # Fetch our own private key for the coin
    bitcoin_addr = input_zero["address"]
    private_key_wif_format = wallet.export_private_key(bitcoin_addr, password)
    private_key_int_format = int.from_bytes(
        Base58.decode_check(private_key_wif_format)[
            1:33], byteorder="big")

    # Grab the outpoint  (the colon is intentionally ommitted from the string)
    outpoint_string = str(
        input_zero["prevout_hash"]) + str(input_zero["prevout_n"])

    # Format the pubkey in preparation to get the shared secret
    scanpubkey_bytes = bytes.fromhex(paycode_field_scan_pubkey)

    # Calculate shared secret
    shared_secret = _calculate_paycode_shared_secret(
        private_key_int_format, scanpubkey_bytes, outpoint_string)

    # Get the real destination for the transaction
    rpa_destination_address = _generate_address_from_pubkey_and_secret(bytes.fromhex(paycode_field_spend_pubkey),
                                                                       shared_secret).to_string(
        Address.FMT_CASHADDR)

    # Swap the dummy destination for the real destination
    tx.rpa_paycode_swap_dummy_for_destination(
        rpa_dummy_address, rpa_destination_address)

    # Now we need to sign the transaction after the outputs are known
    grind_string = paycode_field_scan_pubkey[2:prefix_chars + 2].upper()
    wallet.sign_transaction(tx, password)

    # Setup wallet and keystore in preparation for signature grinding
    my_keystore = wallet.get_keystore()

    # We assume one signature per input, for now...
    assert len(input_zero["signatures"]) == 1
    input_zero["signatures"] = [None]

    # Keypair logic from transaction module
    keypairs = my_keystore.get_tx_derivations(tx)
    for k, v in keypairs.items():
        keypairs[k] = my_keystore.get_private_key(v, password)
    txin = input_zero
    pubkeys, x_pubkeys = tx.get_sorted_pubkeys(txin)
    for j, (pubkey, x_pubkey) in enumerate(zip(pubkeys, x_pubkeys)):
        if pubkey in keypairs:
            _pubkey = pubkey
            kname = 'pubkey'
        elif x_pubkey in keypairs:
            _pubkey = x_pubkey
            kname = 'x_pubkey'
        else:
            continue
        sec, compressed = keypairs.get(_pubkey)

    # Get the keys and preimage ready for signing
    pubkey = public_key_from_private_key(sec, compressed)
    nHashType = 0x00000041  # hardcoded, perhaps should be taken from unsigned input dict
    pre_hash = Hash(bfh(tx.serialize_preimage(0, nHashType, use_cache=False)))

    # While loop for grinding.  Keep grinding until txid prefix matches
    # paycode scanpubkey prefix.
    grind_count = 0
    progress_count = 0

    if progress_callback:
        progress_callback(progress_count)

    while not tx_matches_paycode_prefix:
        if exit_event:
            if exit_event.is_set():
                break

        grind_nonce_string = str(grind_count)
        grinding_message = paycode_hex + grind_nonce_string + grinding_version
        ndata = sha256(grinding_message)
        # Re-sign the transaction input.
        tx._sign_txin(0, 0, sec, compressed, use_cache=False, ndata=ndata)

        if progress_callback and progress_count < grind_count // 1000:
            progress_count = grind_count // 1000
            progress_callback(progress_count)

        input_zero = tx._inputs[0]
        my_serialized_input = tx.serialize_input(input_zero, tx.input_script(input_zero, False, tx._sign_schnorr))
        my_serialized_input_bytes = bytes.fromhex(my_serialized_input)
        hashed_input = sha256(sha256(my_serialized_input_bytes)).hex()
        if hashed_input[0:prefix_chars].upper(
        ) == paycode_field_scan_pubkey[2:prefix_chars + 2].upper():
            tx_matches_paycode_prefix = True

        grind_count += 1

    # Sort the inputs and outputs deterministically
    tx.BIP_LI01_sort()

    # Re-seriliaze the transaction.
    tx.raw = tx.serialize()
    retval = tx.as_dict()["hex"]

    # Return a raw transaction string
    return retval


def extract_private_keys_from_transaction(wallet, raw_tx, password=None):
    # Initialize return value.  Will return empty list if no private key can be found.
    retval = [] 

    # Deserialize the raw transaction
    unpacked_tx = Transaction.deserialize(Transaction(raw_tx))

    # Get a list of output addresses (we will need this for later to check if
    # our key matches)
    output_addresses = []
    outputs = unpacked_tx["outputs"]
    for i in outputs:
        if isinstance(i['address'], Address):
            output_addresses.append(
                i['address'].to_string(
                    Address.FMT_CASHADDR))

    # Variables for looping
    number_of_inputs = len(unpacked_tx["inputs"])
    input_index = 0
    process_inputs = True

    # Process each input until we find one that creates the shared secret to
    # get a private key for an output
    while process_inputs:

        # Grab the outpoint
        single_input = unpacked_tx["inputs"][input_index]
        prevout_hash = single_input["prevout_hash"]
        prevout_n = str(single_input["prevout_n"])  # n is int. convert to str.
        outpoint_string = prevout_hash + prevout_n

        # Get the pubkey of the sender from the scriptSig.
        scriptSig = bytes.fromhex(single_input["scriptSig"])
        d = {}
        parsed_scriptSig = transaction.parse_scriptSig(d, scriptSig)

        sender_pubkey = None
        if "pubkeys" in d:
            sender_pubkey_string = d["pubkeys"][0]
            if isinstance(sender_pubkey_string, str):
                if all(c in "0123456789ABCDEFabcdef" for c in sender_pubkey_string):
                    sender_pubkey = bytes.fromhex(d["pubkeys"][0])

        if sender_pubkey is None:
            # exit early.  This scriptsig either doesn't have a key (coinbase
            # tx, etc), or the xpubkey in the scriptsig is not a hex string
            # (P2PK etc)
            input_index += 1
            if input_index >= number_of_inputs:
                process_inputs = False
            continue

        sender_pubkey = bytes.fromhex(d["pubkeys"][0])

        # We need the private key that corresponds to the scanpubkey.
        # In this implementation, this is the one that goes with receiving
        # address 0
        scanpubkey = wallet.derive_pubkeys(0, 0)

        scan_private_key_wif_format = wallet.export_private_key_from_index(
            (False, 0), password)

        scan_private_key_int_format = int.from_bytes(Base58.decode_check(scan_private_key_wif_format)[1:33],
                                                     byteorder="big")
        # Calculate shared secret
        shared_secret = _calculate_paycode_shared_secret(
            scan_private_key_int_format, sender_pubkey, outpoint_string)

        # Get the spendpubkey for our paycode.
        # In this implementation, simply: receiving address 1.
        spendpubkey = wallet.derive_pubkeys(0, 1)

        # Get the destination address for the transaction
        destination = _generate_address_from_pubkey_and_secret(bytes.fromhex(spendpubkey), shared_secret).to_string(
            Address.FMT_CASHADDR)

        # Fetch our own private (spend) key out of the wallet.
        spendpubkey = wallet.derive_pubkeys(0, 1)
        spend_private_key_wif_format = wallet.export_private_key_from_index(
            (False, 1), password)
        spend_private_key_int_format = int.from_bytes(Base58.decode_check(spend_private_key_wif_format)[1:33],
                                                      byteorder="big")
        # Generate the private key for the money being received via paycode
        privkey = _generate_privkey_from_secret(bytes.fromhex(
            hex(spend_private_key_int_format)[2:]), shared_secret)

        # Now convert to WIF
        extendedkey = "80" + privkey
        extendedkey_bytes = bytes.fromhex(extendedkey)
        checksum = bitcoin.Hash(extendedkey).hex()[0:8]
        key_with_checksum = extendedkey + checksum
        privkey_wif = bitcoin.EncodeBase58Check(extendedkey_bytes)

        # Check the address matches
        if destination in output_addresses:
            retval.append(privkey_wif)
            
        # Increment the input
        input_index += 1

        # If this was the last input, stop.
        if input_index >= number_of_inputs:
            process_inputs = False

    return retval
