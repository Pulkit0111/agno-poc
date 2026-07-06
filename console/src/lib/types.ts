export type Me = { email: string; is_admin: boolean };

export type Approval = {
  id: number;
  user_id: string;
  action: string;
  summary: string;
  created: number;
  status?: "pending" | "approved" | "dismissed";
  decided_by?: string | null;
  payload?: string | null;
};

export type Job = {
  id: number;
  kind: string;
  status: string;
  created: number;
  user_id?: string;
  args?: string;
  attempts?: number;
  error?: string | null;
};
