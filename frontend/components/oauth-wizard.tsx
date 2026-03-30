"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Progress } from "@/components/ui/progress"
import { Check, ExternalLink, Loader2 } from "lucide-react"

const steps = [
  { id: 1, name: "Select Integration", description: "Choose a service to connect" },
  { id: 2, name: "Authorize", description: "Grant access to your account" },
  { id: 3, name: "Configure", description: "Set up sync preferences" },
  { id: 4, name: "Complete", description: "Connection established" },
]

const integrations = [
  {
    id: "quickbooks",
    name: "QuickBooks Online",
    description: "Sync invoices, customers, and payments",
    icon: "/integrations/quickbooks.svg",
  },
  {
    id: "xero",
    name: "Xero",
    description: "Connect your Xero accounting",
    icon: "/integrations/xero.svg",
  },
  {
    id: "google_drive",
    name: "Google Drive",
    description: "Backup invoices to Google Drive",
    icon: "/integrations/google-drive.svg",
  },
  {
    id: "plaid",
    name: "Plaid",
    description: "Bank account verification",
    icon: "/integrations/plaid.svg",
  },
]

interface OAuthWizardProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function OAuthWizard({ open, onOpenChange }: OAuthWizardProps) {
  const [currentStep, setCurrentStep] = useState(1)
  const [selectedIntegration, setSelectedIntegration] = useState<string | null>(null)
  const [isConnecting, setIsConnecting] = useState(false)
  const [syncEnabled, setSyncEnabled] = useState(true)
  const [autoSyncFrequency, setAutoSyncFrequency] = useState("daily")

  const handleSelectIntegration = (id: string) => {
    setSelectedIntegration(id)
    setCurrentStep(2)
  }

  const handleAuthorize = async () => {
    setIsConnecting(true)
    await new Promise((resolve) => setTimeout(resolve, 2000))
    setIsConnecting(false)
    setCurrentStep(3)
  }

  const handleComplete = () => {
    setCurrentStep(4)
    setTimeout(() => {
      onOpenChange(false)
      resetWizard()
    }, 2000)
  }

  const resetWizard = () => {
    setCurrentStep(1)
    setSelectedIntegration(null)
    setIsConnecting(false)
    setSyncEnabled(true)
    setAutoSyncFrequency("daily")
  }

  const progress = (currentStep / 4) * 100

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Connect Integration</DialogTitle>
          <DialogDescription>
            Follow the steps to connect your preferred service
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <Progress value={progress} className="h-2" />
          
          <div className="flex justify-between text-xs text-gray-500">
            {steps.map((step) => (
              <span
                key={step.id}
                className={currentStep >= step.id ? "text-blue-600 font-medium" : ""}
              >
                {step.name}
              </span>
            ))}
          </div>

          {currentStep === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-500">Select an integration to connect:</p>
              <div className="grid gap-3">
                {integrations.map((integration) => (
                  <button
                    key={integration.id}
                    onClick={() => handleSelectIntegration(integration.id)}
                    className="flex items-center gap-4 rounded-lg border p-4 text-left hover:bg-gray-50 transition-colors"
                  >
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100">
                      <Check className="h-5 w-5 text-gray-400" />
                    </div>
                    <div>
                      <p className="font-medium">{integration.name}</p>
                      <p className="text-sm text-gray-500">{integration.description}</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {currentStep === 2 && (
            <div className="space-y-4">
              <div className="text-center py-8">
                <div className="mb-4 flex justify-center">
                  <div className="flex h-16 w-16 items-center justify-center rounded-full bg-blue-100">
                    <ExternalLink className="h-8 w-8 text-blue-600" />
                  </div>
                </div>
                <h3 className="text-lg font-semibold">Authorize Connection</h3>
                <p className="text-sm text-gray-500 mt-2">
                  You will be redirected to {selectedIntegration} to authorize access.
                </p>
              </div>
              <div className="flex gap-3">
                <Button variant="outline" onClick={() => setCurrentStep(1)} className="flex-1">
                  Back
                </Button>
                <Button onClick={handleAuthorize} disabled={isConnecting} className="flex-1">
                  {isConnecting ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Connecting...
                    </>
                  ) : (
                    "Connect"
                  )}
                </Button>
              </div>
            </div>
          )}

          {currentStep === 3 && (
            <div className="space-y-4">
              <h3 className="font-semibold">Configure Sync Settings</h3>
              
              <div className="flex items-center justify-between">
                <Label>Enable automatic sync</Label>
                <input
                  type="checkbox"
                  checked={syncEnabled}
                  onChange={(e) => setSyncEnabled(e.target.checked)}
                  className="h-4 w-4"
                />
              </div>
              
              {syncEnabled && (
                <div className="space-y-2">
                  <Label>Sync Frequency</Label>
                  <select
                    value={autoSyncFrequency}
                    onChange={(e) => setAutoSyncFrequency(e.target.value)}
                    className="w-full rounded-md border border-gray-300 p-2"
                  >
                    <option value="hourly">Hourly</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                  </select>
                </div>
              )}
              
              <div className="flex gap-3 pt-4">
                <Button variant="outline" onClick={() => setCurrentStep(2)} className="flex-1">
                  Back
                </Button>
                <Button onClick={handleComplete} className="flex-1">
                  Complete Setup
                </Button>
              </div>
            </div>
          )}

          {currentStep === 4 && (
            <div className="text-center py-8">
              <div className="mb-4 flex justify-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
                  <Check className="h-8 w-8 text-green-600" />
                </div>
              </div>
              <h3 className="text-lg font-semibold">Connection Successful!</h3>
              <p className="text-sm text-gray-500 mt-2">
                Your {selectedIntegration} integration has been connected.
              </p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
