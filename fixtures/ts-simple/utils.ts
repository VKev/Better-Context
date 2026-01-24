/**
 * Utility functions for ts-simple fixture.
 * 
 * This is a leaf module - no internal dependencies.
 */

export function formatName(name: string): string {
  return name.trim().split(' ').map(part => 
    part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()
  ).join(' ');
}

export function calculateTotal(price: number, quantity: number): number {
  return price * quantity;
}

export function validateEmail(email: string): boolean {
  return email.includes('@') && email.includes('.');
}

export function generateId(): number {
  return Math.floor(Math.random() * 1000000);
}
