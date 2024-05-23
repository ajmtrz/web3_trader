# %%
from web3 import Web3
from web3.gas_strategies.rpc import rpc_gas_price_strategy
from uniswap import Uniswap
import requests
from dotenv import load_dotenv
import os
import json
import time
from datetime import datetime, timezone
import numpy as np

# %%
class TokenTrader:
    def __init__(self, rpc_url, etherscan_api_key, wallet_address, private_key, uniswap_contract_address, 
                 token_input_address, token_output_address, token_presale_contract_address, presale_id):
        self.rpc_url = rpc_url
        self.web3 = Web3(Web3.HTTPProvider(rpc_url))
        self.web3.eth.set_gas_price_strategy(rpc_gas_price_strategy)
        self.etherscan_api_key = etherscan_api_key
        self.wallet_address = wallet_address
        self.private_key = private_key
        # Init Web3 objects
        self.uniswap_contract_address = self.web3.to_checksum_address(uniswap_contract_address)
        self.uniswap_swap_contract_abi = self.get_contract_abi(self.uniswap_contract_address)
        self.uniswap_swap_contract_object = self.web3.eth.contract(address=self.uniswap_contract_address, abi=self.uniswap_swap_contract_abi)
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
            # Comprueba si la solicitud fue exitosa y si hay un ABI disponible
            if response_json['status'] == '1' and response_json['message'] == 'OK':
                abi = json.loads(response_json['result'])
                return abi
        except Exception as e:
            print(f"Ha ocurrido un error al obtener el ABI: {e}")
            return None
    
    def claim_tokens(self):
        try:
            # Obtener info
            user_data = self.token_presale_contract_object.functions.userClaimData(self.wallet_address, self.presale_id).call()
            presale_data = self.token_presale_contract_object.functions.presale(self.presale_id).call()
            claim_enabled = presale_data[9]
            claim_at = user_data[1]
            claimable_amount = user_data[2]
            # Obtener la marca de tiempo actual
            current_timestamp = int(datetime.now(tz=timezone.utc).timestamp())
            # Condiciones para hacer reclamo
            if claim_enabled and claim_at > 0 and current_timestamp >= claim_at and claimable_amount > 0:
                print(f"Intentando reclamar {claimable_amount / 10**self.token_input_decimals} {self.token_input_symbol}.")
                while True:
                    try:
                        tx_hash = self.token_presale_contract_object.functions.claimAmount(self.presale_id).transact({
                            'from': self.wallet_address,
                            'gasPrice': self.web3.eth.generate_gas_price()
                        })
                        print(f"Transacción de reclamo enviada con hash: {tx_hash.hex()}")
                        # Esperar a que la transacción sea confirmada
                        tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
                        if tx_receipt.status == 1:
                            print(f"Reclamo realizado! Transacción confirmada: {tx_hash.hex()}")
                            break
                        else:
                            print(f"Transacción de reclamo fallida: {tx_hash.hex()}")
                    except Exception as tx_exception:
                        print(f"Error en la transacción: {tx_exception}")
            else:
                print("No se puede reclamar en este momento.")
        except Exception as e:
            print(f"Error en el reclamo: {e}")
        
    def get_token_balance(self):
        balance = self.token_input_object.functions.balanceOf(self.wallet_address).call()
        return balance / (10 ** self.token_input_decimals)
        
    def get_price(self):
        price = self.uniswap.get_price_input(self.token_input_address, self.token_output_address, 10**self.token_input_decimals)
        return price / 10**self.token_output_decimals
    
    def make_swap(self, qty):
        try:
            print(f"Vendiendo {qty} {self.token_input_symbol} a {self.get_price()} {self.token_output_symbol}")
            # Convertir cantidad a la unidad correcta
            qty = qty * (10 ** self.token_input_decimals)
            while True:
                try:
                    tx_hash = self.uniswap.make_trade(self.token_input_address, self.token_output_address, int(qty))
                    print(f"Esperando por confirmación de la transacción {tx_hash.hex()}")
                    # Esperar a que la transacción sea confirmada
                    tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
                    if tx_receipt.status == 1:
                        print(f"Swap realizado! Transacción confirmada: {tx_hash.hex()}")
                        break
                    else:
                        raise Exception(f"Transacción de swap fallida: {tx_hash.hex()}")
                except Exception as e:
                    print(f"Error en el swap: {e}")
                    # Esperar 5 segundos antes de intentar nuevamente
                    time.sleep(5)
        except Exception as e:
            print(f"Error en la función make_swap: {e}")

    def trade(self):
        while True:
            try:
                print(f'\n{datetime.now(tz=timezone.utc).strftime("%d-%m-%Y %H:%M:%S")}')
                self.claim_tokens()
                balance = self.get_token_balance()
                print(f"Balance actual: {(balance)} {self.token_input_symbol}")
                price_in_usdt = self.get_price()
                print(f"Precio actual: {price_in_usdt} {self.token_output_symbol}")
                if price_in_usdt > 0.04 and balance > 0:
                    self.make_swap(balance)
                else:
                    time.sleep(5)
                    continue
                # Espero 1 segundo
                time.sleep(1)
            except Exception as e:
                print(f"Ha ocurrido un error: {e}")
                time.sleep(1)

# %%
# Configuración
if __name__ == "__main__":
    if load_dotenv():
        rpc_url = "https://rpc.ankr.com/eth"
        etherscan_api_key = os.getenv("ETHERSCAN_API_KEY")
        wallet_address = os.getenv("WALLET_ADDRESS")
        private_key = os.getenv("PRIVATE_KEY")
        uniswap_contract_address = "0x1458770554b8918B970444d8b2c02A47F6dF99A7"
        token_input_address = "0x26EbB8213fb8D66156F1Af8908d43f7e3e367C1d"
        token_output_address = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        token_presale_contract_address = "0x602C90D796D746b97a36f075d9f3b2892B9B07c2"
        presale_id = 2
        token_trader = TokenTrader(rpc_url,
                                etherscan_api_key,
                                wallet_address, 
                                private_key,
                                uniswap_contract_address,
                                token_input_address,
                                token_output_address,
                                token_presale_contract_address,
                                presale_id)
        token_trader.trade()