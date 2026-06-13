import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent } from 'react';
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type DefaultEdgeOptions,
  type Edge,
  type EdgeChange,
  type NodeChange,
  type NodeProps,
  type NodeTypes,
  type ReactFlowInstance,
  type Viewport,
} from '@xyflow/react';
import { AnimatePresence, motion } from 'framer-motion';

import type {
  BackendWorkflowNodeType,
  NodeCatalogItem,
  WorkflowDraft,
  WorkflowNode,
  WorkflowNodeConfigField,
  WorkflowNodeData,
  WorkflowNodeKind,
  WorkflowRunResponse,
  WorkflowValidationIssue,
  WorkflowValidationResponse,
} from './types';

const STORAGE_KEY = 'email-agent.workflow-builder.draft.v1';
const DRAG_DATA_TYPE = 'application/x-email-agent-workflow-node';
const DEFAULT_VIEWPORT: Viewport = { x: 0, y: 0, zoom: 1 };
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? '';
const AUTO_CONNECT_OFFSET_X = 300;
const AUTO_CONNECT_OFFSET_Y = 0;
const INSERT_SHIFT_X = 220;
const EDGE_INSERT_Y_TOLERANCE = 140;

const DEFAULT_EDGE_OPTIONS: DefaultEdgeOptions = {
  animated: true,
  type: 'smoothstep',
  style: {
    stroke: '#71717a',
    strokeWidth: 2.3,
  },
};

const CATEGORY_ACCENTS: Record<NodeCatalogItem['category'], string> = {
  input: '#2563eb',
  llm: '#7c3aed',
  mcp_tool: '#0891b2',
  condition: '#ca8a04',
  output: '#16a34a',
};

const FALLBACK_NODE_CATALOG: NodeCatalogItem[] = [
  withAccent({
    type: 'input.manual',
    label: 'Manual Input',
    category: 'input',
    description: 'Starting values supplied by a user or future API request.',
    configSchema: [
      {
        name: 'inputName',
        label: 'Input name',
        type: 'string',
        required: true,
        multiline: false,
        default: 'request',
      },
      {
        name: 'sampleValue',
        label: 'Sample value',
        type: 'string',
        required: false,
        multiline: true,
        default: 'Summarize my latest important email.',
      },
    ],
    defaultConfig: {
      inputName: 'request',
      sampleValue: 'Summarize my latest important email.',
    },
    inputs: [],
    outputs: ['value'],
  }),
  withAccent({
    type: 'llm.chat',
    label: 'LLM Chat',
    category: 'llm',
    description: 'Prepare a server-side LLM chat call through the approved LLM adapter.',
    configSchema: [
      {
        name: 'systemPrompt',
        label: 'System prompt',
        type: 'string',
        required: true,
        multiline: true,
        default: 'You are a careful email workflow assistant.',
      },
      {
        name: 'userPrompt',
        label: 'User prompt',
        type: 'string',
        required: true,
        multiline: true,
        default: '{{input.manual.request}}',
      },
    ],
    defaultConfig: {
      systemPrompt: 'You are a careful email workflow assistant.',
      userPrompt: '{{input.manual.request}}',
    },
    inputs: ['context'],
    outputs: ['text'],
  }),
  withAccent({
    type: 'gmail.search_messages',
    label: 'Search Gmail',
    category: 'mcp_tool',
    description: 'Search Gmail through the existing approved Docker Gmail MCP service.',
    configSchema: [
      {
        name: 'query',
        label: 'Gmail query',
        type: 'string',
        required: true,
        multiline: true,
        default: 'in:inbox newer_than:7d',
      },
    ],
    defaultConfig: {
      query: 'in:inbox newer_than:7d',
    },
    inputs: ['query'],
    outputs: ['messages'],
  }),
  withAccent({
    type: 'condition.contains',
    label: 'Contains Condition',
    category: 'condition',
    description: 'Route based on whether a configured field contains a configured value.',
    configSchema: [
      {
        name: 'field',
        label: 'Field',
        type: 'string',
        required: true,
        multiline: false,
        default: 'subject',
      },
      {
        name: 'contains',
        label: 'Contains',
        type: 'string',
        required: true,
        multiline: false,
        default: 'urgent',
      },
    ],
    defaultConfig: {
      field: 'subject',
      contains: 'urgent',
    },
    inputs: ['value'],
    outputs: ['true', 'false'],
  }),
  withAccent({
    type: 'output.final',
    label: 'Final Output',
    category: 'output',
    description: 'Collect the final workflow result.',
    configSchema: [
      {
        name: 'outputName',
        label: 'Output name',
        type: 'string',
        required: true,
        multiline: false,
        default: 'result',
      },
    ],
    defaultConfig: {
      outputName: 'result',
    },
    inputs: ['value'],
    outputs: [],
  }),
];

const FALLBACK_CATALOG_BY_TYPE = catalogByType(FALLBACK_NODE_CATALOG);

type RegistryStatus = {
  state: 'loading' | 'connected' | 'fallback';
  message: string;
};

type RunState = {
  status: 'idle' | 'running' | 'blocked' | 'ready';
  message: string;
  steps: string[];
  result: WorkflowRunResponse | null;
};

export default function App() {
  const initialDraft = useMemo(() => loadDraft(), []);
  const [catalog, setCatalog] = useState<NodeCatalogItem[]>(FALLBACK_NODE_CATALOG);
  const [registryStatus, setRegistryStatus] = useState<RegistryStatus>({
    state: 'loading',
    message: 'Loading backend registry',
  });
  const [nodes, setNodes, onNodesChange] = useNodesState<WorkflowNode>(
    initialDraft?.nodes ?? [],
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialDraft?.edges ?? []);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance<WorkflowNode, Edge> | null>(null);
  const canvasAreaRef = useRef<HTMLElement | null>(null);
  const pointerDragNodeType = useRef<WorkflowNodeKind | null>(null);
  const [saveStatus, setSaveStatus] = useState(() =>
    initialDraft ? `Loaded ${formatTime(initialDraft.savedAt)}` : 'Ready',
  );
  const [validationResult, setValidationResult] = useState<WorkflowValidationResponse | null>(null);
  const [validationStatus, setValidationStatus] = useState('Not validated');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [runState, setRunState] = useState<RunState>({
    status: 'idle',
    message: 'Run has not started',
    steps: [],
    result: null,
  });

  const catalogByNodeType = useMemo(() => catalogByType(catalog), [catalog]);
  const validationIssuesByNode = useMemo(() => issuesByNode(validationResult), [validationResult]);
  const nodeTypes = useMemo<NodeTypes>(
    () => ({
      workflowNode: (props) => (
        <WorkflowNodeCard
          {...props}
          catalogByNodeType={catalogByNodeType}
          validationIssues={validationIssuesByNode[props.id] ?? []}
        />
      ),
    }),
    [catalogByNodeType, validationIssuesByNode],
  );

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId],
  );

  const markDraftChanged = useCallback(() => {
    setSaveStatus('Unsaved changes');
    setValidationResult(null);
    setValidationError(null);
    setValidationStatus('Needs check');
    setRunState({
      status: 'idle',
      message: 'Run has not started',
      steps: [],
      result: null,
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    async function loadRegistry() {
      try {
        const response = await fetch(apiPath('/workflow-node-types'), {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Registry request failed with ${response.status}`);
        }
        const payload = (await response.json()) as BackendWorkflowNodeType[];
        if (!Array.isArray(payload) || payload.length === 0) {
          throw new Error('Registry returned no node types');
        }
        setCatalog(payload.map(withAccent));
        setRegistryStatus({
          state: 'connected',
          message: 'Registry connected',
        });
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        setCatalog(FALLBACK_NODE_CATALOG);
        setRegistryStatus({
          state: 'fallback',
          message: `Fallback registry: ${errorMessage(error)}`,
        });
      }
    }

    loadRegistry();
    return () => controller.abort();
  }, []);

  const addCatalogNode = useCallback(
    (nodeType: WorkflowNodeKind, position?: { x: number; y: number }) => {
      const catalogItem = catalogByNodeType[nodeType];
      if (!catalogItem) {
        return;
      }
      const canvasBounds = canvasAreaRef.current?.getBoundingClientRect();
      const canvasCenter = canvasBounds
        ? {
            x: canvasBounds.left + canvasBounds.width / 2,
            y: canvasBounds.top + canvasBounds.height / 2,
          }
        : { x: window.innerWidth / 2, y: window.innerHeight / 2 };
      const centerPosition = flowInstance
        ? flowInstance.screenToFlowPosition(canvasCenter)
        : { x: 120 + nodes.length * 44, y: 140 + nodes.length * 24 };
      const candidatePosition = position ?? centerPosition;
      const insertionPlan = position
        ? findInsertionPlan(nodes, edges, catalogByNodeType, catalogItem, candidatePosition)
        : null;
      const connectionPlan = findAutoConnectionPlan(
        nodes,
        edges,
        selectedNodeId,
        catalogByNodeType,
        catalogItem,
        candidatePosition,
      );
      const fallbackPosition = connectionPlan
        ? {
            x:
              connectionPlan.newNodeRole === 'target'
                ? connectionPlan.node.position.x + AUTO_CONNECT_OFFSET_X
                : connectionPlan.node.position.x - AUTO_CONNECT_OFFSET_X,
            y: connectionPlan.node.position.y + AUTO_CONNECT_OFFSET_Y,
          }
        : centerPosition;
      const requestedPosition = position ?? fallbackPosition;
      const finalPosition = insertionPlan
        ? {
            x: insertionPlan.x,
            y: insertionPlan.y,
          }
        : connectionPlan
        ? {
            x:
              connectionPlan.newNodeRole === 'target'
                ? Math.max(requestedPosition.x, connectionPlan.node.position.x + AUTO_CONNECT_OFFSET_X)
                : Math.min(requestedPosition.x, connectionPlan.node.position.x - AUTO_CONNECT_OFFSET_X),
            y: requestedPosition.y,
          }
        : requestedPosition;
      const node = createWorkflowNode(
        `node-${nodeType.replace(/[^a-z0-9]+/gi, '-')}-${Date.now()}`,
        catalogItem,
        finalPosition,
      );
      if (insertionPlan) {
        setNodes((currentNodes) =>
          currentNodes
            .map((currentNode) =>
              shouldShiftForInsertion(currentNode, insertionPlan, nodes)
                ? {
                    ...currentNode,
                    position: {
                      ...currentNode.position,
                      x: currentNode.position.x + INSERT_SHIFT_X,
                    },
                  }
                : currentNode,
            )
            .concat(node),
        );
        setEdges((currentEdges) =>
          currentEdges
            .filter((edge) => edge.id !== insertionPlan.edge.id)
            .concat(
              createWorkflowEdge(insertionPlan.edge.source, node.id),
              createWorkflowEdge(node.id, insertionPlan.edge.target),
            ),
        );
      } else {
        setNodes((currentNodes) => [...currentNodes, node]);
      }
      if (!insertionPlan && connectionPlan) {
        setEdges((currentEdges) =>
          addEdge(
            createWorkflowEdge(
              connectionPlan.newNodeRole === 'source' ? node.id : connectionPlan.node.id,
              connectionPlan.newNodeRole === 'source' ? connectionPlan.node.id : node.id,
            ),
            currentEdges,
          ),
        );
      }
      setSelectedNodeId(node.id);
      markDraftChanged();
      window.requestAnimationFrame(() => {
        flowInstance?.fitView({ padding: 0.28, duration: 260 });
      });
    },
    [catalogByNodeType, edges, flowInstance, markDraftChanged, nodes, selectedNodeId, setEdges, setNodes],
  );

  const onPaletteDragStart = useCallback((event: DragEvent<HTMLElement>, nodeType: WorkflowNodeKind) => {
    pointerDragNodeType.current = null;
    event.dataTransfer.setData(DRAG_DATA_TYPE, nodeType);
    event.dataTransfer.effectAllowed = 'copy';
  }, []);

  const onPalettePointerDown = useCallback((event: PointerEvent<HTMLElement>, nodeType: WorkflowNodeKind) => {
    if (event.button !== 0) {
      return;
    }
    pointerDragNodeType.current = nodeType;
  }, []);

  useEffect(() => {
    function handlePointerUp(event: globalThis.PointerEvent) {
      const nodeType = pointerDragNodeType.current;
      pointerDragNodeType.current = null;
      if (!nodeType || !flowInstance || !canvasAreaRef.current) {
        return;
      }
      const bounds = canvasAreaRef.current.getBoundingClientRect();
      const isInsideCanvas =
        event.clientX >= bounds.left &&
        event.clientX <= bounds.right &&
        event.clientY >= bounds.top &&
        event.clientY <= bounds.bottom;
      if (!isInsideCanvas) {
        return;
      }
      addCatalogNode(
        nodeType,
        flowInstance.screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        }),
      );
    }

    window.addEventListener('pointerup', handlePointerUp);
    return () => window.removeEventListener('pointerup', handlePointerUp);
  }, [addCatalogNode, flowInstance]);

  const onCanvasDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }, []);

  const onCanvasDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const nodeType = event.dataTransfer.getData(DRAG_DATA_TYPE);
      if (!nodeType || !flowInstance) {
        return;
      }
      addCatalogNode(
        nodeType,
        flowInstance.screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        }),
      );
    },
    [addCatalogNode, flowInstance],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) {
        return;
      }
      setEdges((currentEdges) =>
        addEdge(
          createWorkflowEdge(connection.source, connection.target, connection.sourceHandle, connection.targetHandle),
          currentEdges,
        ),
      );
      markDraftChanged();
    },
    [markDraftChanged, setEdges],
  );

  const updateSelectedNodeData = useCallback(
    (updates: Partial<WorkflowNodeData>) => {
      if (!selectedNodeId) {
        return;
      }
      setNodes((currentNodes) =>
        currentNodes.map((node) =>
          node.id === selectedNodeId
            ? {
                ...node,
                data: {
                  ...node.data,
                  ...updates,
                  config: updates.config ?? node.data.config,
                },
              }
            : node,
        ),
      );
      markDraftChanged();
    },
    [markDraftChanged, selectedNodeId, setNodes],
  );

  const updateSelectedConfig = useCallback(
    (key: string, value: string) => {
      if (!selectedNode) {
        return;
      }
      updateSelectedNodeData({
        config: {
          ...selectedNode.data.config,
          [key]: value,
        },
      });
    },
    [selectedNode, updateSelectedNodeData],
  );

  const saveDraft = useCallback(() => {
    const savedAt = new Date().toISOString();
    const payload: WorkflowDraft = {
      version: 1,
      nodes,
      edges,
      viewport: flowInstance?.getViewport() ?? DEFAULT_VIEWPORT,
      savedAt,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    setSaveStatus(`Saved ${formatTime(savedAt)}`);
  }, [edges, flowInstance, nodes]);

  const requestValidation = useCallback(async () => {
    const response = await fetch(apiPath('/workflows/validate'), {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
      },
      body: JSON.stringify(createValidationPayload(nodes, edges, flowInstance?.getViewport() ?? DEFAULT_VIEWPORT)),
    });
    if (!response.ok) {
      throw new Error(`Validation request failed with ${response.status}`);
    }
    return (await response.json()) as WorkflowValidationResponse;
  }, [edges, flowInstance, nodes]);

  const restoreDraft = useCallback(() => {
    const draft = loadDraft();
    if (!draft) {
      setSaveStatus('No saved draft found');
      return;
    }
    setNodes(draft.nodes);
    setEdges(draft.edges);
    setSelectedNodeId(null);
    setValidationResult(null);
    setValidationError(null);
    setValidationStatus('Not validated');
    setRunState({
      status: 'idle',
      message: 'Run has not started',
      steps: [],
      result: null,
    });
    window.requestAnimationFrame(() => {
      flowInstance?.setViewport(draft.viewport);
    });
    setSaveStatus(`Restored draft saved ${formatTime(draft.savedAt)}`);
  }, [flowInstance, setEdges, setNodes]);

  const resetDraft = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setNodes([]);
    setEdges([]);
    setSelectedNodeId(null);
    setValidationResult(null);
    setValidationError(null);
    setValidationStatus('Not validated');
    setRunState({
      status: 'idle',
      message: 'Run has not started',
      steps: [],
      result: null,
    });
    window.requestAnimationFrame(() => {
      flowInstance?.setViewport(DEFAULT_VIEWPORT);
    });
    setSaveStatus('New workflow');
  }, [flowInstance, setEdges, setNodes]);

  const validateDraft = useCallback(async () => {
    setIsValidating(true);
    setValidationError(null);
    setValidationStatus('Validating draft');
    try {
      const result = await requestValidation();
      setValidationResult(result);
      setValidationStatus(result.valid ? 'Validation passed' : 'Validation failed');
    } catch (error) {
      setValidationResult(null);
      setValidationError(errorMessage(error));
      setValidationStatus('Validation unavailable');
    } finally {
      setIsValidating(false);
    }
  }, [requestValidation]);

  const runWorkflow = useCallback(async () => {
    setIsValidating(true);
    setValidationError(null);
    setRunState({
      status: 'running',
      message: 'Running preview',
      steps: ['Preparing workflow', 'Checking required fields and connections'],
      result: null,
    });
    try {
      const response = await fetch(apiPath('/workflows/run'), {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify(createValidationPayload(nodes, edges, flowInstance?.getViewport() ?? DEFAULT_VIEWPORT)),
      });
      if (!response.ok) {
        throw new Error(`Run request failed with ${response.status}`);
      }
      const runResult = (await response.json()) as WorkflowRunResponse;
      setValidationResult(runResult.validation);
      setValidationStatus(runResult.valid ? 'Validation passed' : 'Validation failed');
      if (!runResult.valid) {
        setRunState({
          status: 'blocked',
          message: 'Fix validation issues before running',
          steps: [
            'Workflow check failed',
            `${runResult.validation.errors.length} error${runResult.validation.errors.length === 1 ? '' : 's'} found`,
          ],
          result: runResult,
        });
        return;
      }
      setRunState({
        status: 'ready',
        message: 'Preview run complete',
        steps: runResult.steps.map((step) => `${step.label}: ${step.summary}`),
        result: runResult,
      });
    } catch (error) {
      setValidationResult(null);
      setValidationError(errorMessage(error));
      setValidationStatus('Run unavailable');
      setRunState({
        status: 'blocked',
        message: 'Unable to start run',
        steps: ['Workflow check could not complete'],
        result: null,
      });
    } finally {
      setIsValidating(false);
    }
  }, [edges, flowInstance, nodes]);

  return (
    <div className="app-shell">
      <WorkflowToolbar
        registryStatus={registryStatus}
        saveStatus={saveStatus}
        validationResult={validationResult}
        validationStatus={validationStatus}
        validationError={validationError}
        isValidating={isValidating}
        onSave={saveDraft}
        onRestore={restoreDraft}
        onReset={resetDraft}
        onValidate={validateDraft}
        onRun={runWorkflow}
      />
      <div className="builder-grid">
        <NodePalette
          catalog={catalog}
          onAddNode={addCatalogNode}
          onDragStart={onPaletteDragStart}
          onPointerDown={onPalettePointerDown}
        />
        <main ref={canvasAreaRef} className="canvas-area" aria-label="Workflow canvas">
          {nodes.length === 0 ? (
            <div className="canvas-empty" aria-hidden="true">
              <strong>Start with an input</strong>
              <span>Build left to right: Input, action, output, then Run.</span>
            </div>
          ) : null}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
            fitView={!initialDraft}
            fitViewOptions={{ padding: 0.28 }}
            connectionRadius={36}
            connectOnClick
            panOnScroll={false}
            preventScrolling={false}
            zoomOnScroll={false}
            zoomOnPinch
            selectionOnDrag
            deleteKeyCode={['Backspace', 'Delete']}
            onNodesChange={(changes) => {
              onNodesChange(changes);
              if (hasPersistedNodeChanges(changes)) {
                markDraftChanged();
              }
            }}
            onNodeDragStop={(_, draggedNode) => {
              setEdges((currentEdges) =>
                normalizeEdgesForLayout(
                  currentEdges,
                  nodes.map((node) =>
                    node.id === draggedNode.id ? { ...node, position: draggedNode.position } : node,
                  ),
                  catalogByNodeType,
                ),
              );
            }}
            onEdgesChange={(changes) => {
              onEdgesChange(changes);
              if (hasPersistedEdgeChanges(changes)) {
                markDraftChanged();
              }
            }}
            onConnect={onConnect}
            onDragOver={onCanvasDragOver}
            onDrop={onCanvasDrop}
            onInit={(instance) => {
              setFlowInstance(instance);
              if (initialDraft?.viewport) {
                instance.setViewport(initialDraft.viewport);
              } else {
                instance.fitView({ padding: 0.25 });
              }
            }}
            onSelectionChange={({ nodes: selectedNodes }) => {
              setSelectedNodeId(selectedNodes[0]?.id ?? null);
            }}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#d7dde7" gap={20} />
            <MiniMap pannable zoomable nodeStrokeWidth={3} />
            <Controls position="bottom-left" />
          </ReactFlow>
        </main>
        <NodeConfigPanel
          catalogByNodeType={catalogByNodeType}
          selectedNode={selectedNode}
          validationIssues={selectedNode ? validationIssuesByNode[selectedNode.id] ?? [] : []}
          runState={runState}
          onLabelChange={(label) => updateSelectedNodeData({ label })}
          onConfigChange={updateSelectedConfig}
        />
        <WorkflowStatusBar
          nodes={nodes}
          edges={edges}
          selectedNode={selectedNode}
          saveStatus={saveStatus}
          validationResult={validationResult}
          validationStatus={validationStatus}
          validationError={validationError}
          isValidating={isValidating}
          runState={runState}
        />
      </div>
    </div>
  );
}

function WorkflowToolbar({
  registryStatus,
  saveStatus,
  validationResult,
  validationStatus,
  validationError,
  isValidating,
  onSave,
  onRestore,
  onReset,
  onValidate,
  onRun,
}: {
  registryStatus: RegistryStatus;
  saveStatus: string;
  validationResult: WorkflowValidationResponse | null;
  validationStatus: string;
  validationError: string | null;
  isValidating: boolean;
  onSave: () => void;
  onRestore: () => void;
  onReset: () => void;
  onValidate: () => void;
  onRun: () => void;
}) {
  const issueCount = validationResult ? validationResult.errors.length + validationResult.warnings.length : 0;
  const statusLabel = validationError
    ? 'Check unavailable'
    : isValidating
      ? 'Checking'
      : validationResult
        ? validationResult.valid
          ? 'Checked'
          : `${issueCount} ${issueCount === 1 ? 'issue' : 'issues'}`
        : validationStatus === 'Needs check'
          ? 'Needs check'
          : 'Not checked';

  return (
    <header className="toolbar">
      <div className="toolbar-title">
        <BrandMark />
        <h1>Workflow Studio</h1>
        <span className={`toolbar-chip toolbar-chip-${registryStatus.state}`}>{registryStatus.message}</span>
      </div>
      <div className="toolbar-actions">
        <span className="save-status">{saveStatus}</span>
        <span
          className={[
            'validation-chip',
            validationResult?.valid ? 'validation-chip-success' : '',
            validationResult && !validationResult.valid ? 'validation-chip-error' : '',
            validationError ? 'validation-chip-error' : '',
          ]
            .filter(Boolean)
            .join(' ')}
          role="status"
        >
          {statusLabel}
        </span>
        <button type="button" className="secondary-button" title="Load saved draft" onClick={onRestore}>
          <Icon name="load" />
          Load
        </button>
        <button type="button" className="secondary-button" title="Start a new workflow" onClick={onReset}>
          <Icon name="new" />
          New
        </button>
        <button type="button" className="secondary-button" title="Check workflow" disabled={isValidating} onClick={onValidate}>
          <Icon name="check" />
          {isValidating ? 'Checking' : 'Check'}
        </button>
        <button type="button" className="secondary-button" title="Save draft" onClick={onSave}>
          <Icon name="save" />
          Save
        </button>
        <button type="button" className="primary-button" title="Run workflow" disabled={isValidating} onClick={onRun}>
          <Icon name="run" />
          Run
        </button>
      </div>
    </header>
  );
}

function NodePalette({
  catalog,
  onAddNode,
  onDragStart,
  onPointerDown,
}: {
  catalog: NodeCatalogItem[];
  onAddNode: (nodeType: WorkflowNodeKind) => void;
  onDragStart: (event: DragEvent<HTMLElement>, nodeType: WorkflowNodeKind) => void;
  onPointerDown: (event: PointerEvent<HTMLElement>, nodeType: WorkflowNodeKind) => void;
}) {
  const [query, setQuery] = useState('');
  const normalizedQuery = query.trim().toLowerCase();
  const visibleCatalog = normalizedQuery
    ? catalog.filter((item) =>
        [item.label, item.type, item.category, item.description].some((value) =>
          value.toLowerCase().includes(normalizedQuery),
        ),
      )
    : catalog;

  return (
    <aside className="node-palette" aria-label="Node palette">
      <div className="panel-heading">
        <h2>Tools</h2>
        <p>Drag a tool onto the canvas or click to append it.</p>
      </div>
      <label className="palette-search">
        <span>Search tools</span>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Gmail, LLM, condition..." />
      </label>
      <div className="palette-list">
        {visibleCatalog.map((item) => (
          <button
            key={item.type}
            type="button"
            aria-label={`Add ${item.label}`}
            className="palette-item"
            draggable
            onClick={() => onAddNode(item.type)}
            onPointerDown={(event) => onPointerDown(event, item.type)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onAddNode(item.type);
              }
            }}
            onDragStart={(event) => onDragStart(event, item.type)}
          >
            <span className="tool-icon" style={{ color: item.accent }}>
              <ToolIcon item={item} />
            </span>
            <span>
              <strong>{item.label}</strong>
              <small>{formatCategory(item.category)}</small>
            </span>
          </button>
        ))}
        {visibleCatalog.length === 0 ? <div className="empty-state empty-state-compact">No matching tools</div> : null}
      </div>
    </aside>
  );
}

function NodeConfigPanel({
  catalogByNodeType,
  selectedNode,
  validationIssues,
  runState,
  onLabelChange,
  onConfigChange,
}: {
  catalogByNodeType: Record<string, NodeCatalogItem>;
  selectedNode: WorkflowNode | null;
  validationIssues: WorkflowValidationIssue[];
  runState: RunState;
  onLabelChange: (label: string) => void;
  onConfigChange: (key: string, value: string) => void;
}) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    setShowAdvanced(false);
  }, [selectedNode?.id]);

  if (!selectedNode) {
    return (
      <aside className="config-panel" aria-label="Node configuration">
        <div className="panel-heading">
          <h2>Inspector</h2>
          <p>Select a node to edit it.</p>
        </div>
        <div className="empty-state">No node selected</div>
        <RunOutputPanel runState={runState} />
      </aside>
    );
  }

  const catalogItem = catalogByNodeType[selectedNode.data.nodeType] ?? unknownCatalogItem(selectedNode.data.nodeType);
  const configFields = configFieldsForNode(catalogItem, selectedNode);
  const primaryFields = configFields.filter((field) => !isAdvancedConfigField(field, selectedNode.data.nodeType));
  const advancedFields = configFields.filter((field) => isAdvancedConfigField(field, selectedNode.data.nodeType));
  const visibleFields = showAdvanced ? configFields : primaryFields;

  return (
    <aside className="config-panel" aria-label="Node configuration">
      <div className="panel-heading">
        <h2>Inspector</h2>
        <p>{catalogItem.description}</p>
      </div>
      <div className="selected-node-meta">
        <span className="tool-icon tool-icon-small" style={{ color: catalogItem.accent }}>
          <ToolIcon item={catalogItem} />
        </span>
        <span>{formatCategory(catalogItem.category)}</span>
      </div>
      <label className="field">
        <span>Step name</span>
        <input value={selectedNode.data.label} onChange={(event) => onLabelChange(event.target.value)} />
      </label>
      {visibleFields.map((field) => (
        <ConfigField
          key={field.name}
          field={field}
          nodeType={selectedNode.data.nodeType}
          value={selectedNode.data.config[field.name] ?? ''}
          onChange={(value) => onConfigChange(field.name, value)}
        />
      ))}
      {advancedFields.length > 0 ? (
        <button type="button" className="advanced-toggle" onClick={() => setShowAdvanced((value) => !value)}>
          {showAdvanced ? 'Hide advanced settings' : `Show ${advancedFields.length} advanced setting${advancedFields.length === 1 ? '' : 's'}`}
        </button>
      ) : null}
      {configFields.length === 0 ? <div className="empty-state empty-state-compact">No editable fields</div> : null}
      {validationIssues.length > 0 ? (
        <IssueList heading="Node validation" issues={validationIssues} tone="error" />
      ) : null}
      <RunOutputPanel runState={runState} selectedNodeId={selectedNode.id} />
    </aside>
  );
}

function RunOutputPanel({
  runState,
  selectedNodeId,
}: {
  runState: RunState;
  selectedNodeId?: string;
}) {
  const runResult = runState.result;
  const matchingSteps = selectedNodeId && runResult
    ? runResult.steps.filter((step) => step.node_id === selectedNodeId)
    : runResult?.steps ?? [];
  const visibleSteps = matchingSteps.length > 0 ? matchingSteps : runResult?.steps ?? [];
  const heading = selectedNodeId && matchingSteps.length > 0 ? 'Node result' : 'Run results';

  return (
    <section className="run-output-panel" aria-label="Run results">
      <div className="run-output-heading">
        <strong>{heading}</strong>
        {runResult ? <span>{runResult.status === 'completed' ? 'Complete' : 'Blocked'}</span> : null}
      </div>
      {!runResult ? (
        <p>{runState.status === 'running' ? runState.message : 'Click Run to preview each step output.'}</p>
      ) : visibleSteps.length === 0 ? (
        <p>Fix validation issues, then run again.</p>
      ) : (
        <AnimatePresence initial={false}>
          {visibleSteps.map((step) => (
            <motion.article
              key={step.node_id}
              className="run-output-step"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
            >
              <div>
                <strong>{step.label}</strong>
                <span>{step.summary}</span>
              </div>
              <pre>{formatRunOutput(step.output)}</pre>
            </motion.article>
          ))}
        </AnimatePresence>
      )}
    </section>
  );
}

function ConfigField({
  field,
  nodeType,
  value,
  onChange,
}: {
  field: WorkflowNodeConfigField;
  nodeType: WorkflowNodeKind;
  value: string;
  onChange: (value: string) => void;
}) {
  if (field.type === 'boolean') {
    return (
      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={value === 'true'}
          onChange={(event) => onChange(event.target.checked ? 'true' : 'false')}
        />
        <span>{fieldLabelFor(field, nodeType)}</span>
      </label>
    );
  }

  return (
    <label className="field">
      <span>
        {fieldLabelFor(field, nodeType)}
        {field.required ? <strong aria-label="required"> *</strong> : null}
      </span>
      {field.multiline || field.type === 'object' ? (
        <textarea
          value={value}
          placeholder={fieldPlaceholderFor(field, nodeType)}
          onChange={(event) => onChange(event.target.value)}
          rows={compactRowsForField(field, nodeType)}
        />
      ) : (
        <input
          type={field.type === 'number' ? 'number' : 'text'}
          value={value}
          placeholder={fieldPlaceholderFor(field, nodeType)}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </label>
  );
}

function WorkflowStatusBar({
  nodes,
  edges,
  selectedNode,
  saveStatus,
  validationResult,
  validationStatus,
  validationError,
  isValidating,
  runState,
}: {
  nodes: WorkflowNode[];
  edges: Edge[];
  selectedNode: WorkflowNode | null;
  saveStatus: string;
  validationResult: WorkflowValidationResponse | null;
  validationStatus: string;
  validationError: string | null;
  isValidating: boolean;
  runState: RunState;
}) {
  const issueCount = validationResult ? validationResult.errors.length + validationResult.warnings.length : 0;
  const checkLabel = validationError
    ? 'Check unavailable'
    : isValidating
      ? 'Checking workflow'
      : validationResult
        ? validationResult.valid
          ? 'Checked'
          : `${issueCount} ${issueCount === 1 ? 'issue' : 'issues'}`
        : 'Not checked';

  return (
    <section className="status-bar" aria-label="Workflow status" aria-live="polite">
      <Metric label="Tools" value={nodes.length.toString()} />
      <Metric label="Connections" value={edges.length.toString()} />
      <Metric label="Selected" value={selectedNode?.data.label ?? 'None'} />
      <Metric label="Save" value={saveStatus} />
      <Metric label="Check" value={checkLabel} tone={validationResult?.valid ? 'success' : issueCount || validationError ? 'error' : 'neutral'} />
      <ValidationSummary result={validationResult} error={validationError} status={validationStatus} />
      <RunSummary runState={runState} />
    </section>
  );
}

function RunSummary({ runState }: { runState: RunState }) {
  const title = runState.status === 'idle' ? 'Results' : runState.message;
  const idleCopy = 'Click Run to preview each step output.';
  const visibleSteps = runState.result?.steps.slice(0, 3).map((step) => `${step.label}: ${step.summary}`) ?? runState.steps;
  return (
    <div className={`run-summary run-summary-${runState.status}`}>
      <strong>{title}</strong>
      {visibleSteps.length > 0 ? (
        <ol>
          {visibleSteps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      ) : (
        <span>{idleCopy}</span>
      )}
    </div>
  );
}

function ValidationSummary({
  result,
  error,
  status,
}: {
  result: WorkflowValidationResponse | null;
  error: string | null;
  status: string;
}) {
  if (error) {
    return (
      <div className="validation-summary validation-summary-error">
        <strong>Validation unavailable</strong>
        <span>{error}</span>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="validation-summary">
        <strong>{status === 'Needs check' ? 'Changes need check' : 'No issues shown'}</strong>
        <span>{status === 'Needs check' ? 'Run Check when you want backend validation.' : 'Build your flow, then check it.'}</span>
      </div>
    );
  }

  if (result.valid && result.warnings.length === 0) {
    return (
      <div className="validation-summary validation-summary-success">
        <strong>Valid workflow</strong>
        <span>The backend validator accepted this draft.</span>
      </div>
    );
  }

  const issues = [...result.errors, ...result.warnings].slice(0, 4);
  return (
    <div className={`validation-summary ${result.valid ? 'validation-summary-warning' : 'validation-summary-error'}`}>
      <strong>
        {result.errors.length} errors, {result.warnings.length} warnings
      </strong>
      <ul>
        {issues.map((issue) => (
          <li key={`${issue.code}-${issue.node_id ?? issue.edge_id ?? issue.field ?? issue.message}`}>
            {issue.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

function IssueList({
  heading,
  issues,
  tone,
}: {
  heading: string;
  issues: WorkflowValidationIssue[];
  tone: 'error' | 'warning';
}) {
  return (
    <div className={`issue-list issue-list-${tone}`}>
      <strong>{heading}</strong>
      <ul>
        {issues.map((issue) => (
          <li key={`${issue.code}-${issue.field ?? issue.message}`}>{issue.message}</li>
        ))}
      </ul>
    </div>
  );
}

function Metric({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: 'neutral' | 'success' | 'error' }) {
  return (
    <div className={`metric metric-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function WorkflowNodeCard({
  data,
  selected,
  catalogByNodeType,
  validationIssues,
}: NodeProps & {
  catalogByNodeType: Record<string, NodeCatalogItem>;
  validationIssues: WorkflowValidationIssue[];
}) {
  const nodeData = data as WorkflowNodeData;
  const catalogItem = catalogByNodeType[nodeData.nodeType] ?? unknownCatalogItem(nodeData.nodeType);
  const canReceive = catalogItem.category !== 'input';
  const canSend = catalogItem.category !== 'output';

  return (
    <div
      className={[
        'workflow-node',
        selected ? 'workflow-node-selected' : '',
        validationIssues.length > 0 ? 'workflow-node-invalid' : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {canReceive ? <Handle type="target" position={Position.Left} /> : null}
      <div className="workflow-node-header">
        <span className="tool-icon tool-icon-node" style={{ color: catalogItem.accent }}>
          <ToolIcon item={catalogItem} />
        </span>
        <span>
          <strong>{nodeData.label}</strong>
          <small>{formatCategory(catalogItem.category)}</small>
        </span>
      </div>
      <p>{catalogItem.description}</p>
      {validationIssues.length > 0 ? (
        <span className="node-issue-pill">
          {validationIssues.length} {validationIssues.length === 1 ? 'issue' : 'issues'}
        </span>
      ) : null}
      {canSend ? <Handle type="source" position={Position.Right} /> : null}
    </div>
  );
}

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" role="img">
        <path d="M5 7.5h4.2a3 3 0 0 1 2.5 1.35l.6.9a3 3 0 0 0 2.5 1.35H19" />
        <path d="M5 16.5h4.2a3 3 0 0 0 2.5-1.35l.6-.9a3 3 0 0 1 2.5-1.35H19" />
        <circle cx="5" cy="7.5" r="2" />
        <circle cx="19" cy="12" r="2" />
        <circle cx="5" cy="16.5" r="2" />
      </svg>
    </span>
  );
}

function Icon({ name }: { name: 'load' | 'new' | 'check' | 'save' | 'run' }) {
  return (
    <svg className="button-icon" viewBox="0 0 24 24" aria-hidden="true">
      {name === 'load' ? (
        <>
          <path d="M4 12a8 8 0 1 0 2.35-5.65" />
          <path d="M4 4v5h5" />
        </>
      ) : null}
      {name === 'new' ? (
        <>
          <path d="M12 5v14" />
          <path d="M5 12h14" />
        </>
      ) : null}
      {name === 'check' ? <path d="m5 12 4 4L19 6" /> : null}
      {name === 'save' ? (
        <>
          <path d="M5 5h11l3 3v11H5z" />
          <path d="M8 5v6h8" />
          <path d="M8 19v-5h8v5" />
        </>
      ) : null}
      {name === 'run' ? <path d="M8 5v14l11-7z" /> : null}
    </svg>
  );
}

function ToolIcon({ item }: { item: NodeCatalogItem }) {
  const iconName = iconNameForNode(item);
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {iconName === 'input' ? (
        <>
          <path d="M4 12h12" />
          <path d="m12 8 4 4-4 4" />
          <path d="M20 5v14" />
        </>
      ) : null}
      {iconName === 'llm' ? (
        <>
          <path d="M12 4v3" />
          <path d="M12 17v3" />
          <path d="M4 12h3" />
          <path d="M17 12h3" />
          <rect x="7" y="7" width="10" height="10" rx="3" />
          <path d="M10 11h4" />
          <path d="M10 14h3" />
        </>
      ) : null}
      {iconName === 'gmail' ? (
        <>
          <rect x="4" y="6" width="16" height="12" rx="2" />
          <path d="m5 8 7 5 7-5" />
        </>
      ) : null}
      {iconName === 'condition' ? (
        <>
          <path d="M6 4h12v6H6z" />
          <path d="M12 10v4" />
          <path d="M8 20h8" />
          <path d="M8 14h8l-2 6h-4z" />
        </>
      ) : null}
      {iconName === 'output' ? (
        <>
          <path d="M4 5v14" />
          <path d="M8 12h12" />
          <path d="m16 8 4 4-4 4" />
        </>
      ) : null}
      {iconName === 'tool' ? (
        <>
          <path d="M6 6h12v12H6z" />
          <path d="M9 3v3" />
          <path d="M15 3v3" />
          <path d="M9 18v3" />
          <path d="M15 18v3" />
        </>
      ) : null}
    </svg>
  );
}

function createWorkflowNode(id: string, catalogItem: NodeCatalogItem, position: { x: number; y: number }): WorkflowNode {
  return {
    id,
    type: 'workflowNode',
    position,
    data: {
      label: catalogItem.label,
      nodeType: catalogItem.type,
      config: defaultConfigFor(catalogItem),
    },
  };
}

function createWorkflowEdge(
  source: string,
  target: string,
  sourceHandle?: string | null,
  targetHandle?: string | null,
): Edge {
  return {
    ...DEFAULT_EDGE_OPTIONS,
    id: `edge-${source}-${target}-${Date.now()}`,
    source,
    target,
    sourceHandle,
    targetHandle,
  };
}

function findAutoConnectionPlan(
  nodes: WorkflowNode[],
  edges: Edge[],
  selectedNodeId: string | null,
  catalogByNodeType: Record<string, NodeCatalogItem>,
  targetCatalogItem: NodeCatalogItem,
  targetPosition: { x: number; y: number },
): { node: WorkflowNode; newNodeRole: 'source' | 'target' } | null {
  if (nodes.length === 0) {
    return null;
  }

  const selectedNode = selectedNodeId ? nodes.find((node) => node.id === selectedNodeId) : null;
  if (targetCatalogItem.category === 'input') {
    if (selectedNode && canReceiveInto(selectedNode, catalogByNodeType)) {
      return { node: selectedNode, newNodeRole: 'source' };
    }
    const incomingNodeIds = new Set(edges.map((edge) => edge.target));
    const candidates = nodes.filter((node) => canReceiveInto(node, catalogByNodeType));
    const startCandidates = candidates.filter((node) => !incomingNodeIds.has(node.id));
    return nearestNode(startCandidates.length > 0 ? startCandidates : candidates, targetPosition, 'source');
  }

  if (selectedNode && canSendFrom(selectedNode, catalogByNodeType)) {
    return { node: selectedNode, newNodeRole: 'target' };
  }
  const outgoingNodeIds = new Set(edges.map((edge) => edge.source));
  const compatibleNodes = nodes.filter((node) => canSendFrom(node, catalogByNodeType));
  const terminalNodes = compatibleNodes.filter((node) => !outgoingNodeIds.has(node.id));
  return nearestNode(terminalNodes.length > 0 ? terminalNodes : compatibleNodes, targetPosition, 'target');
}

function findInsertionPlan(
  nodes: WorkflowNode[],
  edges: Edge[],
  catalogByNodeType: Record<string, NodeCatalogItem>,
  insertedCatalogItem: NodeCatalogItem,
  position: { x: number; y: number },
): { edge: Edge; x: number; y: number } | null {
  if (!canReceiveCategory(insertedCatalogItem) || !canSendCategory(insertedCatalogItem)) {
    return null;
  }

  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const candidates = edges
    .map((edge) => {
      const source = nodesById.get(edge.source);
      const target = nodesById.get(edge.target);
      if (!source || !target) {
        return null;
      }
      if (!canSendFrom(source, catalogByNodeType) || !canReceiveInto(target, catalogByNodeType)) {
        return null;
      }
      const leftX = Math.min(source.position.x, target.position.x);
      const rightX = Math.max(source.position.x, target.position.x);
      const xDistance = position.x < leftX ? leftX - position.x : position.x > rightX ? position.x - rightX : 0;
      const edgeY = (source.position.y + target.position.y) / 2;
      const yDistance = Math.abs(position.y - edgeY);
      if (xDistance > INSERT_SHIFT_X || yDistance > EDGE_INSERT_Y_TOLERANCE) {
        return null;
      }
      const edgeX = (source.position.x + target.position.x) / 2;
      return {
        edge,
        x: edgeX,
        y: edgeY,
        score: xDistance * 1.4 + yDistance + Math.abs(position.x - edgeX) * 0.15,
      };
    })
    .filter((candidate): candidate is { edge: Edge; x: number; y: number; score: number } => Boolean(candidate))
    .sort((a, b) => a.score - b.score);

  return candidates[0] ? { edge: candidates[0].edge, x: candidates[0].x, y: candidates[0].y } : null;
}

function shouldShiftForInsertion(
  node: WorkflowNode,
  insertionPlan: { edge: Edge; x: number; y: number },
  nodesBeforeInsertion: WorkflowNode[],
): boolean {
  const target = nodesBeforeInsertion.find((candidate) => candidate.id === insertionPlan.edge.target);
  if (!target) {
    return false;
  }
  return node.position.x >= target.position.x - 8;
}

function nearestNode(
  nodes: WorkflowNode[],
  targetPosition: { x: number; y: number },
  newNodeRole: 'source' | 'target',
): { node: WorkflowNode; newNodeRole: 'source' | 'target' } | null {
  const node = nodes
    .map((candidate) => ({
      node: candidate,
      distance: squaredDistance(candidate.position, targetPosition),
    }))
    .sort((a, b) => a.distance - b.distance)[0]?.node;
  return node ? { node, newNodeRole } : null;
}

function normalizeEdgesForLayout(
  edges: Edge[],
  nodes: WorkflowNode[],
  catalogByNodeType: Record<string, NodeCatalogItem>,
): Edge[] {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  return edges.map((edge) => {
    const source = nodesById.get(edge.source);
    const target = nodesById.get(edge.target);
    if (!source || !target) {
      return edge;
    }
    const isVisuallyReversed = source.position.x > target.position.x + 44;
    const canReverse = canSendFrom(target, catalogByNodeType) && canReceiveInto(source, catalogByNodeType);
    if (!isVisuallyReversed || !canReverse) {
      return edge;
    }
    return {
      ...edge,
      id: `edge-${target.id}-${source.id}-${Date.now()}`,
      source: target.id,
      target: source.id,
      sourceHandle: edge.targetHandle,
      targetHandle: edge.sourceHandle,
    };
  });
}

function canSendFrom(node: WorkflowNode, catalogByNodeType: Record<string, NodeCatalogItem>): boolean {
  const catalogItem = catalogByNodeType[node.data.nodeType] ?? unknownCatalogItem(node.data.nodeType);
  return canSendCategory(catalogItem);
}

function canReceiveInto(node: WorkflowNode, catalogByNodeType: Record<string, NodeCatalogItem>): boolean {
  const catalogItem = catalogByNodeType[node.data.nodeType] ?? unknownCatalogItem(node.data.nodeType);
  return canReceiveCategory(catalogItem);
}

function canSendCategory(catalogItem: NodeCatalogItem): boolean {
  return catalogItem.category !== 'output';
}

function canReceiveCategory(catalogItem: NodeCatalogItem): boolean {
  return catalogItem.category !== 'input';
}

function squaredDistance(a: { x: number; y: number }, b: { x: number; y: number }): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return dx * dx + dy * dy;
}

function defaultConfigFor(catalogItem: NodeCatalogItem): Record<string, string> {
  const config = Object.fromEntries(
    catalogItem.configSchema.map((field) => [
      field.name,
      stringifyConfigValue(field.default ?? catalogItem.defaultConfig[field.name] ?? ''),
    ]),
  );
  for (const [key, value] of Object.entries(catalogItem.defaultConfig)) {
    config[key] = config[key] ?? stringifyConfigValue(value);
  }
  return config;
}

function loadDraft(): WorkflowDraft | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as WorkflowDraft;
    if (parsed.version !== 1 || !Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) {
      return null;
    }
    const nodes = parsed.nodes.filter(isWorkflowNode);
    if (nodes.length !== parsed.nodes.length) {
      return null;
    }
    return {
      version: 1,
      nodes,
      edges: parsed.edges.map(normalizeSavedEdge),
      viewport: parsed.viewport ?? DEFAULT_VIEWPORT,
      savedAt: parsed.savedAt ?? new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

function normalizeSavedEdge(edge: Edge): Edge {
  const edgeWithMarkers = edge as Edge & { markerEnd?: unknown; markerStart?: unknown };
  const { markerEnd: _markerEnd, markerStart: _markerStart, ...cleanEdge } = edgeWithMarkers;
  return {
    ...DEFAULT_EDGE_OPTIONS,
    ...cleanEdge,
    animated: true,
    type: 'smoothstep',
    style: DEFAULT_EDGE_OPTIONS.style,
  };
}

function isWorkflowNode(node: WorkflowNode): node is WorkflowNode {
  const nodeType = node?.data?.nodeType;
  return Boolean(
    node?.id &&
      node?.type === 'workflowNode' &&
      node?.position &&
      typeof nodeType === 'string' &&
      typeof node.data.label === 'string' &&
      node.data.config &&
      typeof node.data.config === 'object',
  );
}

function createValidationPayload(nodes: WorkflowNode[], edges: Edge[], viewport: Viewport): WorkflowDraft {
  return {
    version: 1,
    viewport,
    nodes: nodes.map((node) => ({
      id: node.id,
      type: node.type,
      position: node.position,
      data: {
        label: node.data.label,
        nodeType: node.data.nodeType,
        config: node.data.config,
      },
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
    })),
  };
}

function configFieldsForNode(catalogItem: NodeCatalogItem, node: WorkflowNode): WorkflowNodeConfigField[] {
  const fieldsByName = new Map(catalogItem.configSchema.map((field) => [field.name, field]));
  for (const configKey of Object.keys(node.data.config)) {
    if (!fieldsByName.has(configKey)) {
      fieldsByName.set(configKey, {
        name: configKey,
        label: formatFieldLabel(configKey),
        type: 'string',
        required: false,
        multiline: configKey.toLowerCase().includes('prompt'),
      });
    }
  }
  return Array.from(fieldsByName.values());
}

function withAccent(nodeType: BackendWorkflowNodeType): NodeCatalogItem {
  return {
    ...nodeType,
    accent: CATEGORY_ACCENTS[nodeType.category] ?? '#64748b',
  };
}

function catalogByType(catalog: NodeCatalogItem[]): Record<string, NodeCatalogItem> {
  return catalog.reduce<Record<string, NodeCatalogItem>>((acc, item) => {
    acc[item.type] = item;
    return acc;
  }, {});
}

function unknownCatalogItem(nodeType: string): NodeCatalogItem {
  return {
    type: nodeType,
    label: 'Unknown Node',
    category: 'condition',
    description: 'This node type is not present in the loaded backend registry.',
    configSchema: [],
    defaultConfig: {},
    inputs: [],
    outputs: [],
    accent: '#64748b',
  };
}

function issuesByNode(result: WorkflowValidationResponse | null): Record<string, WorkflowValidationIssue[]> {
  if (!result) {
    return {};
  }
  const byNode: Record<string, WorkflowValidationIssue[]> = {};
  for (const issue of [...result.errors, ...result.warnings]) {
    if (!issue.node_id) {
      continue;
    }
    byNode[issue.node_id] = [...(byNode[issue.node_id] ?? []), issue];
  }
  return byNode;
}

function hasPersistedNodeChanges(changes: NodeChange<WorkflowNode>[]): boolean {
  return changes.some((change) => change.type !== 'dimensions' && change.type !== 'select');
}

function hasPersistedEdgeChanges(changes: EdgeChange<Edge>[]): boolean {
  return changes.some((change) => change.type !== 'select');
}

function apiPath(path: string): string {
  return `${API_BASE_URL}${path}`;
}

function stringifyConfigValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function formatRunOutput(value: unknown): string {
  if (value === null || value === undefined) {
    return 'No output';
  }
  if (typeof value === 'string') {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown error';
}

function formatFieldLabel(value: string): string {
  return value
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[._-]+/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatCategory(value: NodeCatalogItem['category']): string {
  return value.replace(/_/g, ' ');
}

function isAdvancedConfigField(field: WorkflowNodeConfigField, nodeType: WorkflowNodeKind): boolean {
  const key = field.name.toLowerCase();
  if (key === 'inputname' || key === 'outputname') {
    return true;
  }
  if (nodeType === 'llm.chat' && key === 'systemprompt') {
    return true;
  }
  return key.includes('id') || key.includes('endpoint') || key.includes('adapter');
}

function fieldLabelFor(field: WorkflowNodeConfigField, nodeType: WorkflowNodeKind): string {
  const key = field.name.toLowerCase();
  if (nodeType === 'llm.chat' && key === 'userprompt') {
    return 'Prompt';
  }
  if (nodeType === 'llm.chat' && key === 'systemprompt') {
    return 'Assistant instructions';
  }
  if (nodeType === 'gmail.search_messages' && key === 'query') {
    return 'Search query';
  }
  if (nodeType === 'condition.contains' && key === 'contains') {
    return 'Value to match';
  }
  if (key === 'samplevalue') {
    return 'Example input';
  }
  if (key === 'inputname') {
    return 'Input key';
  }
  if (key === 'outputname') {
    return 'Output key';
  }
  return field.label || formatFieldLabel(field.name);
}

function fieldPlaceholderFor(field: WorkflowNodeConfigField, nodeType: WorkflowNodeKind): string | undefined {
  if (field.placeholder) {
    return field.placeholder;
  }
  const key = field.name.toLowerCase();
  if (nodeType === 'llm.chat' && key === 'userprompt') {
    return 'Tell the assistant what to do with the previous step.';
  }
  if (nodeType === 'gmail.search_messages' && key === 'query') {
    return 'in:inbox newer_than:7d';
  }
  if (nodeType === 'condition.contains' && key === 'contains') {
    return 'urgent';
  }
  if (key === 'samplevalue') {
    return 'Example text for testing this workflow.';
  }
  return undefined;
}

function compactRowsForField(field: WorkflowNodeConfigField, nodeType: WorkflowNodeKind): number {
  if (nodeType === 'llm.chat' && field.name.toLowerCase() === 'userprompt') {
    return 3;
  }
  return field.multiline || field.type === 'object' ? 3 : 2;
}

function iconNameForNode(item: NodeCatalogItem): 'input' | 'llm' | 'gmail' | 'condition' | 'output' | 'tool' {
  if (item.type.includes('gmail')) {
    return 'gmail';
  }
  if (item.category === 'input') {
    return 'input';
  }
  if (item.category === 'llm') {
    return 'llm';
  }
  if (item.category === 'condition') {
    return 'condition';
  }
  if (item.category === 'output') {
    return 'output';
  }
  return 'tool';
}

function formatTime(value: string | undefined): string {
  if (!value) {
    return 'just now';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return 'just now';
  }
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
