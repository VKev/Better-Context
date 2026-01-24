/**
 * Type definitions for ts-simple fixture.
 * 
 * This is a leaf module - no internal dependencies.
 */

export interface User {
  id: number;
  name: string;
  email: string;
}

export interface Product {
  id: number;
  name: string;
  price: number;
  sku?: string;
}

export interface Order {
  id: number;
  user: User;
  products: Product[];
  total: number;
}

export type UserInput = Omit<User, 'id'>;

export type ProductInput = Omit<Product, 'id'>;
