import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** The server's message from an axios-shaped rejection, else the error's own. */
export function errorMessage(error: unknown, fallback: string): string {
  const axiosLike = error as {
    response?: { data?: { message?: string; error?: string } };
    message?: string;
  };
  return (
    axiosLike?.response?.data?.message ||
    axiosLike?.response?.data?.error ||
    axiosLike?.message ||
    fallback
  );
}
