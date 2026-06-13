import type { Edge, Node, Viewport } from '@xyflow/react';

export type WorkflowNodeKind = string;

export type WorkflowNodeConfigField = {
  name: string;
  label: string;
  type: 'string' | 'object' | 'number' | 'boolean';
  required: boolean;
  multiline: boolean;
  default?: unknown;
  placeholder?: string | null;
};

export type WorkflowNodeTypeCategory = 'input' | 'llm' | 'mcp_tool' | 'condition' | 'output';

export type BackendWorkflowNodeType = {
  type: WorkflowNodeKind;
  label: string;
  category: WorkflowNodeTypeCategory;
  description: string;
  configSchema: WorkflowNodeConfigField[];
  defaultConfig: Record<string, unknown>;
  inputs: string[];
  outputs: string[];
};

export type NodeCatalogItem = BackendWorkflowNodeType & {
  accent: string;
};

export type WorkflowNodeData = Record<string, unknown> & {
  label: string;
  nodeType: WorkflowNodeKind;
  config: Record<string, string>;
};

export type WorkflowNode = Node<WorkflowNodeData, 'workflowNode'>;

export type WorkflowDraft = {
  id?: string;
  name?: string;
  version: 1;
  nodes: WorkflowNode[];
  edges: Edge[];
  viewport: Viewport;
  savedAt?: string;
};

export type WorkflowValidationIssue = {
  code: string;
  message: string;
  node_id?: string | null;
  edge_id?: string | null;
  field?: string | null;
};

export type WorkflowValidationResponse = {
  valid: boolean;
  errors: WorkflowValidationIssue[];
  warnings: WorkflowValidationIssue[];
};

export type WorkflowRunStep = {
  node_id: string;
  node_type: WorkflowNodeKind;
  label: string;
  status: 'success' | 'skipped' | 'error';
  summary: string;
  output: unknown;
};

export type WorkflowRunResponse = {
  run_id: string;
  status: 'completed' | 'blocked';
  valid: boolean;
  validation: WorkflowValidationResponse;
  steps: WorkflowRunStep[];
  result: unknown;
};
