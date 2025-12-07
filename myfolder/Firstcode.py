import random
import string # This module provides useful string constants

def generate_password(length):
    # 1. Define the possible characters
    lower_letters = string.ascii_lowercase
    upper_letters = string.ascii_uppercase
    digits = string.digits
    symbols = string.punctuation

    # 2. Combine all character sets
    all_characters = lower_letters + upper_letters + digits + symbols

    # 3. Ensure the password has at least one of each type
    # We use random.choice() to pick one mandatory character of each type
    password = [
        random.choice(lower_letters),
        random.choice(upper_letters),
        random.choice(digits),
        random.choice(symbols)
    ]

    # 4. Fill the remaining length with random choices from ALL characters
    remaining_length = length - len(password)
    
    # We use random.choices() to pick the rest of the characters
    password.extend(random.choices(all_characters, k=remaining_length))

    # 5. Shuffle the list to randomize the order
    random.shuffle(password)

    # 6. Convert the list of characters back into a string
    return "".join(password)

# Example Usage:
print(generate_password(12)) # Prints a 12-character random password