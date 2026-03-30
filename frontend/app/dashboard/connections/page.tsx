'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Check, X, ExternalLink, RefreshCw, Unlink, Settings, Loader2 } from "lucide-react"
import { api } from '@/lib/api'

interface Connection {
  id: number
  provider: string
  is_active: boolean
  connected_at: string
  expires_at: string | null
  last_synced_at: string | null
}

const providerInfo: Record<string, { name: string; description: string; icon: string }> = {
  quickbooks: { name: "QuickBooks", description: "Sync invoices and payments with QuickBooks Online", icon: "/quickbooks.svg" },
  xero: { name: "Xero", description: "Connect to Xero for accounting integration", icon: "/xero.svg" },
  google: { name: "Google Drive", description: "Automatically backup invoices to Google Drive", icon: "/google.svg" },
  plaid: { name: "Plaid", description: "Connect bank accounts for payment verification", icon: "/plaid.svg" },
  slack: { name: "Slack", description: "Get notifications in Slack for important events", icon: "/slack.svg" },
}

export default function ConnectionsPage() {
  const [connections, setConnections] = useState<Connection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchConnections()
  }, [])

  const fetchConnections = async () => {
    try {
      setLoading(true)
      const data = await api.get<Connection[]>('/api/v1/connections')
      setConnections(data)
    } catch (err) {
      setError('Failed to load connections')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const handleDisconnect = async (provider: string) => {
    try {
      await api.post(`/api/v1/connections/${provider}/disconnect`, {})
      fetchConnections()
    } catch (err) {
      console.error('Failed to disconnect:', err)
    }
  }

  const getProviderStatus = (provider: string) => {
    const conn = connections.find(c => c.provider === provider && c.is_active)
    if (!conn) return { connected: false, lastSync: null, status: 'disconnected' }
    return {
      connected: true,
      lastSync: conn.last_synced_at ? new Date(conn.last_synced_at).toLocaleString() : null,
      status: conn.expires_at && new Date(conn.expires_at) < new Date() ? 'expired' : 'active'
    }
  }

  const allProviders = Object.keys(providerInfo)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Connections</h2>
        <p className="text-muted-foreground">
          Manage your connected accounts and integrations
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {allProviders.map((provider) => {
          const info = providerInfo[provider]
          const status = getProviderStatus(provider)
          
          return (
            <Card key={provider}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-lg">{info.name}</CardTitle>
                {status.connected ? (
                  <Badge variant="default" className="bg-green-600">Connected</Badge>
                ) : (
                  <Badge variant="secondary">Not Connected</Badge>
                )}
              </CardHeader>
              <CardContent>
                <CardDescription className="mb-4">{info.description}</CardDescription>
                {status.connected && status.lastSync && (
                  <p className="text-xs text-muted-foreground mb-4">
                    Last synced: {status.lastSync}
                  </p>
                )}
                <div className="flex gap-2">
                  {status.connected ? (
                    <>
                      <Button 
                        variant="outline" 
                        size="sm" 
                        onClick={() => fetchConnections()}
                      >
                        <RefreshCw className="mr-2 h-4 w-4" />
                        Sync
                      </Button>
                      <Button 
                        variant="outline" 
                        size="sm"
                        onClick={() => handleDisconnect(provider)}
                      >
                        <Unlink className="mr-2 h-4 w-4" />
                        Disconnect
                      </Button>
                    </>
                  ) : (
                    <Button size="sm" asChild>
                      <a href={`/api/v1/oauth/${provider}/authorize`}>
                        Connect
                      </a>
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
