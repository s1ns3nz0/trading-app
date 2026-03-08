import hashlib


class WalletService:
    """
    Mock HD wallet: deterministic address per (user_id, asset).
    In production: replace with BIP-44 key derivation from platform seed.
    """

    _PREFIX: dict[str, str] = {
        "ETH": "0x",
        "BTC": "bc1q",
        "USDT": "0x",
    }

    def generate_address(self, user_id: str, asset: str) -> str:
        digest = hashlib.sha256(f"{user_id}:{asset}".encode()).hexdigest()
        if asset == "BTC":
            return f"bc1q{digest[:38]}"
        return f"0x{digest[:40]}"

    def validate_address(self, address: str, asset: str) -> bool:
        if asset in ("ETH", "USDT"):
            return address.startswith("0x") and len(address) == 42
        if asset == "BTC":
            return address.startswith("bc1q") and len(address) == 42
        return False
