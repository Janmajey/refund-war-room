import re

SEND_WORDS = re.compile(r"\b(send|message|whats\s?app|notify|bhej\w*)\b", re.I)
MONEY = re.compile(r"₹|\brs\.?\s?\d|\binr\b|\bcredit\b|\bpay(?:ing)? out\b", re.I)
LINK = re.compile(r"https?://|www\.|\.[a-z]{2,}/", re.I)


class Gate:
    """Decides, in code, whether a side-effect step may run. The model never gets a vote."""

    def __init__(self, allowed_sellers, max_length=300):
        self.allowed = {int(s) for s in allowed_sellers}
        self.max_length = max_length

    def check(self, step, user_message):
        if step.origin != "user":
            return False, f"requested by {step.origin}, not by the user"
        if not SEND_WORDS.search(user_message):
            return False, "the user did not ask for a message to be sent"
        seller = str(step.args.get("seller_id", ""))
        if not seller.isdigit() or int(seller) not in self.allowed:
            return False, f"seller {seller or '?'} is not on the allow-list"
        if seller not in re.findall(r"\d+", user_message):
            return False, f"seller {seller} is not named in the user's message"
        message = str(step.args.get("message", "")).strip()
        if not message or len(message) > self.max_length:
            return False, f"message must be 1 to {self.max_length} characters"
        if LINK.search(message):
            return False, "messages may not contain links"
        if MONEY.search(message):
            return False, "messages may not promise money; payouts go through finance"
        return True, "ok"
