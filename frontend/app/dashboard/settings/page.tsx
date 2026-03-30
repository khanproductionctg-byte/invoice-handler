'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Separator } from "@/components/ui/separator"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { User, Mail, Building, Key, Bell, Shield, CreditCard, Loader2 } from "lucide-react"
import { api } from '@/lib/api'

interface User {
  id: number
  email: string
  full_name: string
}

interface Tenant {
  id: number
  name: string
  slug: string
  plan: string
  subscription_status: string
}

interface Subscription {
  status: string
  plan_id: string
  current_period_end?: string
}

interface Usage {
  invoices_used: number
  invoices_limit: number
}

interface APIKey {
  id: number
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
}

export default function SettingsPage() {
  const [user, setUser] = useState<User | null>(null)
  const [tenant, setTenant] = useState<Tenant | null>(null)
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [apiKeys, setApiKeys] = useState<APIKey[]>([])
  const [loading, setLoading] = useState(true)

  const [profileForm, setProfileForm] = useState({ firstName: '', lastName: '', email: '' })
  const [orgForm, setOrgForm] = useState({ name: '', website: '', timezone: '' })

  useEffect(() => {
    Promise.all([
      api.get<User>('/auth/users/me/').catch(() => null),
      api.get<Tenant>('/api/v1/tenants/me').catch(() => null),
      api.get<Subscription>('/api/v1/billing/subscription').catch(() => null),
      api.get<Usage>('/api/v1/usage').catch(() => null),
      api.get<APIKey[]>('/api/v1/api-keys').catch(() => []),
    ]).then(([userData, tenantData, subData, usageData, keysData]) => {
      setUser(userData)
      setTenant(tenantData)
      setSubscription(subData)
      setUsage(usageData)
      setApiKeys(keysData)

      if (userData?.full_name) {
        const parts = userData.full_name.split(' ')
        setProfileForm({
          firstName: parts[0] || '',
          lastName: parts.slice(1).join(' ') || '',
          email: userData.email || ''
        })
      } else if (userData?.email) {
        setProfileForm(prev => ({ ...prev, email: userData.email }))
      }

      if (tenantData) {
        setOrgForm(prev => ({ ...prev, name: tenantData.name }))
      }
    }).finally(() => setLoading(false))
  }, [])

  const getInitials = (name: string) => {
    return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2) || 'U'
  }

  const getUsagePercent = () => {
    if (!usage || !usage.invoices_limit) return 0
    return Math.round((usage.invoices_used / usage.invoices_limit) * 100)
  }

  const getPlanPrice = (planId: string) => {
    switch (planId) {
      case 'free': return 0
      case 'pro': return 49
      case 'enterprise': return 199
      default: return 0
    }
  }

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString()
  }

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
        <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500">Manage your account and preferences</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User className="h-5 w-5" />
                Profile
              </CardTitle>
              <CardDescription>Update your personal information</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-4">
                <Avatar className="h-16 w-16">
                  <AvatarFallback className="text-lg">
                    {getInitials(profileForm.firstName + ' ' + profileForm.lastName)}
                  </AvatarFallback>
                </Avatar>
                <Button variant="outline">Change Avatar</Button>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="firstName">First Name</Label>
                  <Input 
                    id="firstName" 
                    value={profileForm.firstName}
                    onChange={(e) => setProfileForm(p => ({ ...p, firstName: e.target.value }))}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="lastName">Last Name</Label>
                  <Input 
                    id="lastName" 
                    value={profileForm.lastName}
                    onChange={(e) => setProfileForm(p => ({ ...p, lastName: e.target.value }))}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input 
                  id="email" 
                  type="email" 
                  value={profileForm.email}
                  onChange={(e) => setProfileForm(p => ({ ...p, email: e.target.value }))}
                  disabled
                />
              </div>
              <Button>Save Changes</Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Building className="h-5 w-5" />
                Organization
              </CardTitle>
              <CardDescription>Manage your organization settings</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="orgName">Organization Name</Label>
                <Input 
                  id="orgName" 
                  value={orgForm.name}
                  onChange={(e) => setOrgForm(p => ({ ...p, name: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="orgWebsite">Website</Label>
                <Input 
                  id="orgWebsite" 
                  value={orgForm.website}
                  onChange={(e) => setOrgForm(p => ({ ...p, website: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="timezone">Timezone</Label>
                <Input 
                  id="timezone" 
                  value={orgForm.timezone}
                  onChange={(e) => setOrgForm(p => ({ ...p, timezone: e.target.value }))}
                />
              </div>
              <Button>Save Changes</Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bell className="h-5 w-5" />
                Notifications
              </CardTitle>
              <CardDescription>Configure how you receive notifications</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <Label>Email Notifications</Label>
                  <p className="text-sm text-gray-500">Receive email for important updates</p>
                </div>
                <Switch defaultChecked />
              </div>
              <Separator />
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <Label>Payment Alerts</Label>
                  <p className="text-sm text-gray-500">Get notified when payments are received</p>
                </div>
                <Switch defaultChecked />
              </div>
              <Separator />
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <Label>Invoice Reminders</Label>
                  <p className="text-sm text-gray-500">Receive reminders for overdue invoices</p>
                </div>
                <Switch defaultChecked />
              </div>
              <Separator />
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <Label>Weekly Reports</Label>
                  <p className="text-sm text-gray-500">Get weekly summary of your invoices</p>
                </div>
                <Switch />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Key className="h-5 w-5" />
                API Keys
              </CardTitle>
              <CardDescription>Manage your API keys for integrations</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {apiKeys.length > 0 ? (
                apiKeys.map((key) => (
                  <div key={key.id} className="rounded-lg border p-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="font-medium">{key.name}</p>
                        <p className="text-sm text-gray-500 font-mono">{key.prefix}...••••••</p>
                      </div>
                      <Badge variant="success">Active</Badge>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-sm text-gray-500">No API keys yet</p>
              )}
              <Button variant="outline">Generate New Key</Button>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CreditCard className="h-5 w-5" />
                Subscription
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-lg bg-blue-50 p-4">
                <p className="font-medium text-blue-900">
                  {(tenant?.plan || 'Free').charAt(0).toUpperCase()}{(tenant?.plan || 'free').slice(1)} Plan
                </p>
                <p className="text-2xl font-bold text-blue-900">
                  ${getPlanPrice(tenant?.plan || 'free')}<span className="text-sm font-normal">/month</span>
                </p>
                {usage && (
                  <p className="text-sm text-blue-700">
                    {usage.invoices_used.toLocaleString()} / {usage.invoices_limit.toLocaleString()} invoices/month
                  </p>
                )}
              </div>
              {usage && (
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">Invoices Used</span>
                    <span>{usage.invoices_used.toLocaleString()} / {usage.invoices_limit.toLocaleString()}</span>
                  </div>
                  <div className="h-2 rounded-full bg-gray-200">
                    <div className="h-2 rounded-full bg-blue-600" style={{ width: `${getUsagePercent()}%` }} />
                  </div>
                </div>
              )}
              <Button className="w-full">Upgrade Plan</Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Shield className="h-5 w-5" />
                Security
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Button variant="outline" className="w-full">Change Password</Button>
              <Button variant="outline" className="w-full">Enable Two-Factor</Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
