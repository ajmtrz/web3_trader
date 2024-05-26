# %%
from web3 import Web3, middleware
#from web3.gas_strategies.rpc import rpc_gas_price_strategy
from web3.gas_strategies.time_based import fast_gas_price_strategy
from web3.middleware import construct_sign_and_send_raw_middleware
from uniswap import Uniswap
import requests
import json
import time
from datetime import datetime, timezone
import numpy as np
import gnupg
import keyring

# %%
class TokenTrader:
    def __init__(self, etherscan_api_key, wallet_address, private_key, token_input_address, 
                 token_output_address, token_presale_contract_address, presale_id):
        self.rpc_url = "https://rpc.ankr.com/eth"
        self.etherscan_api_key = etherscan_api_key
        self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.web3.eth.set_gas_price_strategy(fast_gas_price_strategy)
        self.web3.middleware_onion.add(middleware.time_based_cache_middleware)
        self.web3.middleware_onion.add(middleware.latest_block_based_cache_middleware)
        self.web3.middleware_onion.add(middleware.simple_cache_middleware)
        self.private_key = private_key
        self.wallet_address = self.web3.to_checksum_address(wallet_address)
        self.web3.eth.default_account = self.wallet_address
        self.web3.middleware_onion.add(construct_sign_and_send_raw_middleware(self.private_key))
        # Init Uniswap object
        self.uniswap = Uniswap(address=self.wallet_address, private_key=self.private_key, version=3, web3=self.web3, provider=self.rpc_url)
        # Presale contract
        self.token_presale_contract_address = self.web3.to_checksum_address(token_presale_contract_address)
        self.token_presale_contract_abi = self.get_contract_abi(self.token_presale_contract_address)
        self.token_presale_contract_object = self.web3.eth.contract(address=self.token_presale_contract_address, abi=self.token_presale_contract_abi)
        self.presale_id = presale_id
        # Init Token INPUT objects
        self.token_input_address = self.web3.to_checksum_address(token_input_address)
        self.token_input_abi = self.get_contract_abi(self.token_input_address)
        self.token_input_object = self.web3.eth.contract(address=self.token_input_address, abi=self.token_input_abi)
        self.token_input_symbol = self.token_input_object.functions.symbol().call()
        self.token_input_decimals = self.token_input_object.functions.decimals().call()
        # Init Token OUTPUT objects
        self.token_output_address = self.web3.to_checksum_address(token_output_address)
        self.token_output_abi = self.get_contract_abi(self.token_output_address)
        self.token_output_object = self.web3.eth.contract(address=self.token_output_address, abi=self.token_output_abi)
        self.token_output_symbol = self.token_output_object.functions.symbol().call()
        self.token_output_decimals = self.token_output_object.functions.decimals().call()
     
    def get_contract_abi(self, contract_address):
        try:
            url = f"https://api.etherscan.io/api?module=contract&action=getabi&address={contract_address}&apikey={self.etherscan_api_key}"
            response = requests.get(url)
            response_json = response.json()
            if response_json['status'] == '1' and response_json['message'] == 'OK':
                abi = json.loads(response_json['result'])
                return abi
        except Exception as e:
            print(f"Ha ocurrido un error al obtener el ABI: {e}")
            return None
        
    def staking_balance(self, contract_address, account_address, abi):
        contract = self.web3.eth.contract(address=contract_address, abi=abi)
        balance = contract.functions.getStakingBalance(account_address).call()
        return balance
    
    def stake_tokens(self, contract_address, abi, amount):
        contract = self.web3.eth.contract(address=contract_address, abi=abi)
        tx_hash = contract.functions.stakeTokens(amount).transact()
        tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        if tx_receipt.status == 1:
            print(f"Staking realizado! Transacción confirmada: {tx_hash.hex()}")
        else:
            raise Exception(f"Transacción de staking fallida: {tx_hash.hex()}")

    def unstake_tokens(self, contract_address, abi, amount):
        contract = self.web3.eth.contract(address=contract_address, abi=abi)
        tx_hash = contract.functions.unstakeTokens(amount).transact()
        tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        if tx_receipt.status == 1:
            print(f"Staking realizado! Transacción confirmada: {tx_hash.hex()}")
        else:
            raise Exception(f"Transacción de staking fallida: {tx_hash.hex()}")
        
    def can_claim_tokens(self):
        presale_data = self.token_presale_contract_object.functions.presale(self.presale_id).call()
        user_data = self.token_presale_contract_object.functions.userClaimData(self.wallet_address, self.presale_id).call()
        vesting_data = self.token_presale_contract_object.functions.vesting(self.presale_id).call()
        claim_enabled = presale_data[9]
        claimable_amount = user_data[2]
        claim_count = user_data[5]
        vesting_start_time = vesting_data[0]
        vesting_interval = vesting_data[2]
        total_claim_cycles = vesting_data[4]
        current_timestamp = int(datetime.now(tz=timezone.utc).timestamp())
        # Verificar si está permitido reclamar
        if claim_enabled and claimable_amount > 0 and vesting_start_time > 0:
            if claim_count == 0:
                if current_timestamp >= vesting_start_time:
                    return True
            else:
                duration_since_start = current_timestamp - vesting_start_time
                available_cycles = duration_since_start // vesting_interval
                if available_cycles > claim_count and available_cycles <= total_claim_cycles:
                    return True
        return False
    
    def claim_tokens(self):
        if self.can_claim_tokens():
            print(f"Intentando reclamar...")
            while True:
                try:
                    tx_hash = self.token_presale_contract_object.functions.claimAmount(self.presale_id).transact()
                    print(f"Esperando por confirmación de la transacción de reclamo: {tx_hash.hex()}")
                    tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
                    if tx_receipt.status == 1:
                        print(f"Reclamo realizado! Transacción confirmada: {tx_hash.hex()}")
                        break
                    else:
                        raise Exception(f"Transacción de reclamo fallida: {tx_hash.hex()}")
                except Exception as tx_exception:
                    print(f"Error en el reclamo: {tx_exception}")
                    time.sleep(5)
        else:
            print("No se puede reclamar en este momento.")
    
    def make_swap(self, qty, price):
        print(f"Vendiendo {qty / (10 ** self.token_input_decimals)} {self.token_input_symbol} a {price} {self.token_output_symbol}")
        while True:
            try:
                tx_hash = self.uniswap.make_trade(self.token_input_address, self.token_output_address, qty)
                print(f"Esperando por confirmación de la transacción de swap: {tx_hash.hex()}")
                # Esperar a que la transacción sea confirmada
                tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
                if tx_receipt.status == 1:
                    print(f"Swap realizado! Transacción confirmada: {tx_hash.hex()}")
                    break
                else:
                    raise Exception(f"Transacción de swap fallida: {tx_hash.hex()}")
            except Exception as tx_exception:
                    print(f"Error en el swap: {tx_exception}")
                    time.sleep(5)

    def trade(self):
        while True:
            try:
                if self.web3.is_connected():
                    print(f'\n{datetime.now(tz=timezone.utc).strftime("%d-%m-%Y %H:%M:%S")}')
                    price = (self.uniswap.get_price_input(
                                        self.token_input_address,
                                        self.token_output_address,
                                        10**self.token_input_decimals)
                                    / 10**self.token_output_decimals)
                    print(f"Precio actual: {price} {self.token_output_symbol}")
                    if price > 1.0:
                        self.claim_tokens()
                        balance_int = self.token_input_object.functions.balanceOf(self.wallet_address).call()
                        balance_float = np.round(balance_int / (10 ** self.token_input_decimals), 6)
                        print(f"Balance actual: {balance_float} {self.token_input_symbol}")
                        if balance_float > 0:
                            self.make_swap(balance_int, price)
                    else:
                        # Claim y staking
                        time.sleep(5)
                        continue
                    time.sleep(1)
            except Exception as e:
                print(f"Ha ocurrido un error: {e}")
                time.sleep(1)

# %%
# Configuración
if __name__ == "__main__":
    gpg = gnupg.GPG()
    with open('C:\\Users\\Administrador\\Repositorios\\web3_trader\\.env.gpg', 'rb') as file:
        datos = gpg.decrypt_file(file, passphrase=keyring.get_password("GPG_Passphrase", "gpg_python"))
    if datos.ok:
        env_vars = dict(line.decode('utf-8').split('=', 1) for line in datos.data.splitlines())
        etherscan_api_key = env_vars.get('ETHERSCAN_API_KEY')
        wallet_address = env_vars.get('WALLET_ADDRESS')
        private_key = env_vars.get('PRIVATE_KEY')
        token_input_address = "0x26EbB8213fb8D66156F1Af8908d43f7e3e367C1d"
        token_output_address = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        token_presale_contract_address = "0x602C90D796D746b97a36f075d9f3b2892B9B07c2"
        presale_id = 2
        token_trader = TokenTrader(etherscan_api_key,
                                wallet_address, 
                                private_key,
                                token_input_address,
                                token_output_address,
                                token_presale_contract_address,
                                presale_id)
        token_trader.trade()