# %%
from web3 import Web3
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
                 token_output_address, token_presale_contract_address, uniswap_factory_contract_address, token_prices):
        self.rpc_url = "https://rpc.ankr.com/eth"
        self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.etherscan_api_key = etherscan_api_key
        self.private_key = private_key
        self.wallet_address = self.web3.to_checksum_address(wallet_address)
        self.web3.eth.default_account = self.wallet_address
        self.web3.middleware_onion.add(construct_sign_and_send_raw_middleware(self.private_key))
        # Init Uniswap object
        self.uniswap_factory_contract_address = self.web3.to_checksum_address(uniswap_factory_contract_address)
        self.uniswap = Uniswap(address=self.wallet_address, private_key=self.private_key, version=3, web3=self.web3, provider=self.rpc_url, factory_contract_addr=self.uniswap_factory_contract_address)
        # Presale contract
        self.token_presale_contract_address = self.web3.to_checksum_address(token_presale_contract_address)
        self.token_presale_contract_abi = self.get_contract_abi(self.token_presale_contract_address)
        self.token_presale_contract_object = self.web3.eth.contract(address=self.token_presale_contract_address, abi=self.token_presale_contract_abi)
        self.presale_id = 2
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
        # Prices array
        self.token_prices = token_prices
     
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
        
    def can_claim_tokens(self, presale_data, vesting_data, user_data):
        claim_enabled = presale_data[9]
        vesting_start_time = vesting_data[0]
        vesting_interval = vesting_data[2]
        total_claim_cycles = vesting_data[4]
        claimable_amount = user_data[2]
        claim_count = user_data[5]
        current_timestamp = int(datetime.now(tz=timezone.utc).timestamp())
        # Verificar si está permitido reclamar
        if claim_enabled and claimable_amount > 0:
            # Tiempo hasta siguiente claim
            current_date = datetime.fromtimestamp(current_timestamp)
            future_date = datetime.fromtimestamp(vesting_start_time + vesting_interval * claim_count)
            difference = future_date - current_date
            if current_date < future_date:
                days = difference.days
                seconds = difference.total_seconds()
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                seconds = int(seconds % 60)
                print(f"{days} días, {hours % 24} horas, {minutes} minutos, {seconds} segundos para reclamar")
            # Cantidad en vesting
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
        print(f"Intentando reclamar...")
        try:
            tx_hash = self.token_presale_contract_object.functions.claimAmount(self.presale_id).transact()
            print(f"Esperando por confirmación de la transacción de reclamo: {tx_hash.hex()}")
            tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            if tx_receipt.status == 1:
                print(f"Reclamo realizado! Transacción confirmada: {tx_hash.hex()}")
            else:
                raise Exception(f"Transacción de reclamo fallida: {tx_hash.hex()}")
        except Exception as tx_exception:
            print(f"Error en el reclamo: {tx_exception}")
    
    def make_swap(self, qty, price):
        print(f"Vendiendo {qty / (10 ** self.token_input_decimals)} {self.token_input_symbol} a {price} {self.token_output_symbol}")
        try:
            tx_hash = self.uniswap.make_trade(self.token_input_address, self.token_output_address, qty, fee=3000)
            print(f"Esperando por confirmación de la transacción de swap: {tx_hash.hex()}")
            tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            if tx_receipt.status == 1:
                print(f"Swap realizado! Transacción confirmada: {tx_hash.hex()}")
            else:
                raise Exception(f"Transacción de swap fallida: {tx_hash.hex()}")
        except Exception as tx_exception:
                print(f"Error en el swap: {tx_exception}")

    def trade(self):
        while True:
            try:
                if self.web3.is_connected():
                    presale_data = self.token_presale_contract_object.functions.presale(self.presale_id).call()
                    vesting_data = self.token_presale_contract_object.functions.vesting(self.presale_id).call()
                    user_data = self.token_presale_contract_object.functions.userClaimData(self.wallet_address, self.presale_id).call()
                    claimed_amount = user_data[4]
                    active_percent_amount = user_data[6]
                    threshold_price_count = claimed_amount // active_percent_amount
                    min_sell_price = self.token_prices[threshold_price_count]
                    print(f'\n{datetime.now(tz=timezone.utc).strftime("%d-%m-%Y %H:%M:%S")}')
                    price = (self.uniswap.get_price_input(self.token_input_address, self.token_output_address, 10**self.token_input_decimals, fee=3000)
                             / 10**self.token_output_decimals)
                    print(f"Precio actual: {price} {self.token_output_symbol} | Umbral {threshold_price_count} mínimo: {min_sell_price:.6f} {self.token_output_symbol}")
                    if price > min_sell_price:
                        balance = self.token_input_object.functions.balanceOf(self.wallet_address).call()
                        if balance >= active_percent_amount:
                            self.make_swap(active_percent_amount, price)
                        elif self.can_claim_tokens(presale_data, vesting_data, user_data):
                            self.claim_tokens()
                    time.sleep(1)
                else:
                    raise Exception(f"Error al conectar a la red de Ethereum")
            except Exception as e:
                print(f"Ha ocurrido un error: {e}")
                time.sleep(5)

# %%
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
        uniswap_factory_contract_address = "0x1458770554b8918B970444d8b2c02A47F6dF99A7"
        token_prices_array = np.linspace(0.09, 2.99, 20, endpoint=False)
        token_trader = TokenTrader(etherscan_api_key,
                                wallet_address, 
                                private_key,
                                token_input_address,
                                token_output_address,
                                token_presale_contract_address,
                                uniswap_factory_contract_address,
                                token_prices_array)
        token_trader.trade()