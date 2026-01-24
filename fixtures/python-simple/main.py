"""Main entry point for the python-simple fixture.

This module imports from utils and models to create dependencies.
"""

from utils import format_name, calculate_total
from models import User, Product


def main():
    """Main function demonstrating usage."""
    user = User(name="Alice", email="alice@example.com")
    product = Product(name="Widget", price=9.99)

    print(f"User: {format_name(user.name)}")
    print(f"Product total: ${calculate_total(product.price, 2):.2f}")


if __name__ == "__main__":
    main()
