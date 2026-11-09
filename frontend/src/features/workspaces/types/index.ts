/** A workspace groups documents and conversations (PRD §7.1). */
export interface Workspace {
  id: number;
  name: string;
  is_default: boolean;
  document_count: number;
  conversation_count: number;
  created_at: string;
  updated_at: string;
}
