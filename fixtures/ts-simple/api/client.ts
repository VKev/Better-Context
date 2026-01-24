/**
 * API client for ts-simple fixture.
 * 
 * Imports from types and utils.
 */

import type { User, UserInput } from '../types';
import { generateId } from '../utils';

const API_BASE = 'https://api.example.com';

export async function fetchUser(id: number): Promise<User | null> {
  // Simulated API call
  return {
    id,
    name: 'John Doe',
    email: 'john@example.com',
  };
}

export async function createUser(input: UserInput): Promise<User> {
  return {
    id: generateId(),
    ...input,
  };
}

export async function deleteUser(id: number): Promise<boolean> {
  // Simulated delete
  return true;
}
