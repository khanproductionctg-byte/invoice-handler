"use client"

import { useState, useCallback } from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Check, Play, Loader2, AlertCircle, Calendar } from "lucide-react"
import { api } from "@/lib/api"

interface WorkflowRun {
  id: number;
  invocation_id: string;
  workflow_type: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  current_step?: string;
  progress: number;
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

interface RunWorkflowButtonProps {
  workflowId: string
  workflowName: string
  onRun?: (config: WorkflowConfig) => Promise<void>
}

interface WorkflowConfig {
  invoiceIds?: string[]
  dateRange?: {
    start: string
    end: string
  }
  dryRun: boolean
}

export function RunWorkflowButton({ workflowId, workflowName, onRun }: RunWorkflowButtonProps) {
  const [open, setOpen] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null)
  const [selectedInvoices, setSelectedInvoices] = useState<string[]>([])
  const [dateRange, setDateRange] = useState({ start: "", end: "" })
  const [dryRun, setDryRun] = useState(true)

  const pollWorkflowStatus = useCallback(async (invocationId: string): Promise<WorkflowRun> => {
    const maxAttempts = 60
    const pollInterval = 2000

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      const status = await api.getWorkflowStatus(invocationId)
      if (status.status === 'completed' || status.status === 'failed') {
        return status
      }
      await new Promise((resolve) => setTimeout(resolve, pollInterval))
    }

    throw new Error('Workflow polling timeout')
  }, [])

  const handleRun = async () => {
    setIsRunning(true)
    setResult(null)

    try {
      if (onRun) {
        await onRun({
          invoiceIds: selectedInvoices.length > 0 ? selectedInvoices : undefined,
          dateRange: dateRange.start && dateRange.end ? dateRange : undefined,
          dryRun,
        })
      } else {
        const response = await api.runWorkflow(workflowId, selectedInvoices.length > 0 ? selectedInvoices : undefined)
        const finalStatus = await pollWorkflowStatus(response.invocation_id)

        if (finalStatus.status === 'completed') {
          setResult({ success: true, message: "Workflow completed successfully!" })
        } else if (finalStatus.status === 'failed') {
          setResult({ success: false, message: finalStatus.error_message || "Workflow failed. Please try again." })
        } else {
          setResult({ success: false, message: "Workflow timed out. Please check status later." })
        }
        setIsRunning(false)
        return
      }
      setResult({ success: true, message: "Workflow completed successfully!" })
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Workflow failed. Please try again."
      setResult({ success: false, message: errorMessage })
    } finally {
      setIsRunning(false)
    }
  }

  const handleClose = () => {
    setOpen(false)
    setResult(null)
    setSelectedInvoices([])
    setDateRange({ start: "", end: "" })
    setDryRun(true)
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <Play className="mr-2 h-4 w-4" />
        Run Workflow
      </Button>

      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Run Workflow</DialogTitle>
            <DialogDescription>
              Configure and run the &quot;{workflowName}&quot; workflow
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {result ? (
              <div className={`rounded-lg p-4 ${result.success ? "bg-green-50" : "bg-red-50"}`}>
                <div className="flex items-center gap-2">
                  {result.success ? (
                    <Check className="h-5 w-5 text-green-600" />
                  ) : (
                    <AlertCircle className="h-5 w-5 text-red-600" />
                  )}
                  <p className={result.success ? "text-green-800" : "text-red-800"}>
                    {result.message}
                  </p>
                </div>
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <Label>Invoice IDs (optional)</Label>
                  <Input
                    placeholder="INV-001, INV-002, INV-003"
                    value={selectedInvoices.join(", ")}
                    onChange={(e) =>
                      setSelectedInvoices(
                        e.target.value.split(",").map((s) => s.trim()).filter(Boolean)
                      )
                    }
                  />
                  <p className="text-xs text-gray-500">Leave empty to process all pending invoices</p>
                </div>

                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <Calendar className="h-4 w-4" />
                    Date Range (optional)
                  </Label>
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      type="date"
                      value={dateRange.start}
                      onChange={(e) => setDateRange({ ...dateRange, start: e.target.value })}
                      placeholder="Start date"
                    />
                    <Input
                      type="date"
                      value={dateRange.end}
                      onChange={(e) => setDateRange({ ...dateRange, end: e.target.value })}
                      placeholder="End date"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div>
                    <Label className="text-sm">Dry Run</Label>
                    <p className="text-xs text-gray-500">Preview results without making changes</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={dryRun}
                    onChange={(e) => setDryRun(e.target.checked)}
                    className="h-4 w-4"
                  />
                </div>
              </>
            )}
          </div>

          <DialogFooter>
            {result ? (
              <Button onClick={handleClose}>Close</Button>
            ) : (
              <>
                <Button variant="outline" onClick={handleClose}>
                  Cancel
                </Button>
                <Button onClick={handleRun} disabled={isRunning}>
                  {isRunning ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Running...
                    </>
                  ) : (
                    <>
                      <Play className="mr-2 h-4 w-4" />
                      Run Now
                    </>
                  )}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
