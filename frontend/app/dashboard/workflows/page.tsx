'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Play, Pause, Settings, Trash2, Plus, Workflow, Clock, CheckCircle, Loader2 } from "lucide-react"
import { api } from '@/lib/api'

interface WorkflowRun {
  id: number
  invocation_id: string
  workflow_type: string
  status: string
  current_step: string | null
  progress: number
  error_message: string | null
  created_at: string
  completed_at: string | null
}

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<WorkflowRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)

  useEffect(() => {
    fetchWorkflows()
  }, [])

  const fetchWorkflows = async () => {
    try {
      setLoading(true)
      const data = await api.get<WorkflowRun[]>('/api/v1/workflows')
      setWorkflows(data)
    } catch (err) {
      setError('Failed to load workflows')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const runWorkflow = async (workflowType: string = 'full') => {
    try {
      setRunning(true)
      await api.post<WorkflowRun>('/api/v1/workflows/run', { workflow_type: workflowType })
      await fetchWorkflows()
    } catch (err) {
      console.error('Failed to run workflow:', err)
    } finally {
      setRunning(false)
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return <Badge className="bg-green-600">Completed</Badge>
      case 'running':
        return <Badge className="bg-blue-600">Running</Badge>
      case 'failed':
        return <Badge className="bg-red-600">Failed</Badge>
      case 'queued':
        return <Badge variant="secondary">Queued</Badge>
      default:
        return <Badge variant="outline">{status}</Badge>
    }
  }

  const workflowTemplates = [
    { type: 'full', name: 'Full Pipeline', description: 'Run all steps: ingest, reconcile, chase, report' },
    { type: 'ingestion', name: 'Ingestion Only', description: 'Fetch new invoices from all sources' },
    { type: 'reconciliation', name: 'Reconciliation Only', description: 'Match payments to invoices' },
    { type: 'chasing', name: 'Payment Chasing Only', description: 'Send payment reminders' },
  ]

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Workflows</h2>
          <p className="text-muted-foreground">
            Manage and run automated workflows
          </p>
        </div>
        <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              Run Workflow
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Run Workflow</DialogTitle>
              <DialogDescription>
                Select a workflow to run
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              {workflowTemplates.map((template) => (
                <Card 
                  key={template.type} 
                  className="cursor-pointer hover:bg-accent"
                  onClick={() => {
                    runWorkflow(template.type)
                    setCreateDialogOpen(false)
                  }}
                >
                  <CardHeader className="py-3">
                    <CardTitle className="text-base">{template.name}</CardTitle>
                    <CardDescription className="text-sm">{template.description}</CardDescription>
                  </CardHeader>
                </Card>
              ))}
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          {error}
        </div>
      )}

      <div className="grid gap-4">
        {workflows.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <Workflow className="h-12 w-12 text-muted-foreground mb-4" />
              <p className="text-muted-foreground">No workflows run yet</p>
              <Button className="mt-4" onClick={() => setCreateDialogOpen(true)}>
                Run Your First Workflow
              </Button>
            </CardContent>
          </Card>
        ) : (
          workflows.map((workflow) => (
            <Card key={workflow.id}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <div>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Workflow className="h-5 w-5" />
                    {workflow.workflow_type}
                  </CardTitle>
                  <CardDescription>
                    {workflow.current_step || 'Initializing'} • {workflow.progress}% complete
                  </CardDescription>
                </div>
                {getStatusBadge(workflow.status)}
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4 text-sm text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Clock className="h-4 w-4" />
                      {new Date(workflow.created_at).toLocaleString()}
                    </span>
                    {workflow.completed_at && (
                      <span className="flex items-center gap-1">
                        <CheckCircle className="h-4 w-4" />
                        Completed: {new Date(workflow.completed_at).toLocaleString()}
                      </span>
                    )}
                  </div>
                  {workflow.status === 'failed' && workflow.error_message && (
                    <Badge variant="destructive">{workflow.error_message}</Badge>
                  )}
                </div>
                {workflow.status === 'running' && (
                  <div className="mt-4">
                    <div className="h-2 bg-secondary rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-primary transition-all" 
                        style={{ width: `${workflow.progress}%` }}
                      />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  )
}
