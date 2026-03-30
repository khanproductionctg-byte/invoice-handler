'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { CreditCard, Download, Loader2, Check, X } from "lucide-react"
import { api } from '@/lib/api'

interface Plan {
  id: string
  name: string
  description: string
  price_monthly: number
  price_yearly: number
  features: string[]
}

interface Subscription {
  status: string
  plan_id: string
  current_period_end: string
  card_last4?: string
  card_brand?: string
  card_exp_month?: number
  card_exp_year?: number
}

interface Usage {
  invoices_used: number
  invoices_limit: number
  emails_used: number
  emails_limit: number
  sms_used: number
  sms_limit: number
  api_calls: number
}

interface BillingHistory {
  invoices: Array<{
    id: string
    date: string
    amount: number
    status: string
    currency: string
  }>
}

const defaultPlans: Plan[] = [
  {
    id: "free",
    name: "Free",
    description: "For small teams just getting started",
    price_monthly: 0,
    price_yearly: 0,
    features: [
      "100 invoices/month",
      "1 user",
      "Basic reminders",
      "Email support",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    description: "For growing businesses",
    price_monthly: 29,
    price_yearly: 290,
    features: [
      "5,000 invoices/month",
      "5 users",
      "Advanced reminders",
      "Priority support",
      "AI-powered categorization",
      "Advanced reports",
      "API access",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    description: "For large organizations",
    price_monthly: 99,
    price_yearly: 990,
    features: [
      "Unlimited invoices",
      "Unlimited users",
      "Custom reminders",
      "24/7 phone support",
      "AI-powered categorization",
      "Advanced reports",
      "API access",
      "Custom integrations",
      "Dedicated account manager",
      "SLA guarantee",
    ],
  },
]

const notIncludedFeatures: Record<string, string[]> = {
  free: ["AI-powered categorization", "Advanced reports", "API access", "Custom integrations"],
  pro: ["Custom integrations", "Dedicated account manager"],
  enterprise: [],
}

export default function BillingPage() {
  const [plans, setPlans] = useState<Plan[]>(defaultPlans)
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [billingHistory, setBillingHistory] = useState<BillingHistory | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get<Plan[]>('/api/v1/billing/plans').catch(() => defaultPlans),
      api.get<Subscription>('/api/v1/billing/subscription').catch(() => null),
      api.get<Usage>('/api/v1/usage').catch(() => null),
      api.get<BillingHistory>('/api/v1/billing/history').catch(() => ({ invoices: [] })),
    ]).then(([plansData, subData, usageData, historyData]) => {
      if (Array.isArray(plansData) && plansData.length > 0) {
        setPlans(plansData)
      }
      setSubscription(subData)
      setUsage(usageData)
      setBillingHistory(historyData)
    }).finally(() => {
      setLoading(false)
    })
  }, [])

  const currentPlan = plans.find(p => p.id === subscription?.plan_id) || plans[0]
  
  const getUsagePercent = (used: number, limit: number) => {
    if (limit === 0) return 0
    return Math.min(100, Math.round((used / limit) * 100))
  }

  const formatCurrency = (amount: number, currency: string = 'USD') => {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount / 100)
  }

  const getStatusVariant = (status: string) => {
    switch (status) {
      case 'paid':
      case 'active':
      case 'subscribed':
        return 'success'
      case 'pending':
      case 'past_due':
        return 'warning'
      case 'cancelled':
      case 'expired':
        return 'destructive'
      default:
        return 'secondary'
    }
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Billing</h1>
          <p className="text-gray-500">Manage your subscription and billing</p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {plans.map((plan) => (
          <Card key={plan.name} className={plan.id === currentPlan.id ? "border-blue-500 border-2" : ""}>
            <CardHeader>
              {plan.id === 'pro' && (
                <Badge className="w-fit bg-blue-600">Most Popular</Badge>
              )}
              <CardTitle className="flex items-center gap-2">
                {plan.name}
                {plan.id === currentPlan.id && (
                  <Badge variant="success">Current</Badge>
                )}
              </CardTitle>
              <CardDescription>{plan.description}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <span className="text-4xl font-bold">${plan.price_monthly}</span>
                <span className="text-gray-500">/month</span>
              </div>
              <ul className="space-y-2">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex items-center gap-2 text-sm">
                    <Check className="h-4 w-4 text-green-500" />
                    {feature}
                  </li>
                ))}
                {notIncludedFeatures[plan.id]?.map((feature) => (
                  <li key={feature} className="flex items-center gap-2 text-sm text-gray-400">
                    <X className="h-4 w-4" />
                    {feature}
                  </li>
                ))}
              </ul>
              <Button
                className="w-full"
                variant={plan.id === currentPlan.id ? "outline" : plan.id === "pro" ? "default" : "outline"}
                disabled={plan.id === currentPlan.id}
              >
                {plan.id === currentPlan.id ? "Current Plan" : plan.id === "enterprise" ? "Contact Sales" : "Upgrade"}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      {usage && (
        <Card>
          <CardHeader>
            <CardTitle>Usage This Month</CardTitle>
            <CardDescription>Your current usage statistics</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-6 md:grid-cols-3">
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Invoices</span>
                  <span>{usage.invoices_used.toLocaleString()} / {usage.invoices_limit.toLocaleString()}</span>
                </div>
                <div className="h-2 rounded-full bg-gray-200">
                  <div className="h-2 rounded-full bg-blue-600" style={{ width: `${getUsagePercent(usage.invoices_used, usage.invoices_limit)}%` }} />
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Emails</span>
                  <span>{usage.emails_used.toLocaleString()} / {usage.emails_limit.toLocaleString()}</span>
                </div>
                <div className="h-2 rounded-full bg-gray-200">
                  <div className="h-2 rounded-full bg-blue-600" style={{ width: `${getUsagePercent(usage.emails_used, usage.emails_limit)}%` }} />
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">API Calls</span>
                  <span>{usage.api_calls.toLocaleString()}</span>
                </div>
                <div className="h-2 rounded-full bg-gray-200">
                  <div className="h-2 rounded-full bg-blue-600" style={{ width: "0%" }} />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            Payment Method
          </CardTitle>
          <CardDescription>Manage your payment information</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {subscription?.card_last4 ? (
            <div className="flex items-center justify-between rounded-lg border p-4">
              <div className="flex items-center gap-4">
                <div className="rounded-md bg-gray-100 p-2">
                  <CreditCard className="h-6 w-6" />
                </div>
                <div>
                  <p className="font-medium">
                    {subscription.card_brand?.charAt(0).toUpperCase()}{subscription.card_brand?.slice(1) || 'Card'} ending in {subscription.card_last4}
                  </p>
                  <p className="text-sm text-gray-500">
                    Expires {subscription.card_exp_month}/{subscription.card_exp_year}
                  </p>
                </div>
              </div>
              <Badge variant={getStatusVariant(subscription.status)}>
                {subscription.status === 'active' ? 'Default' : subscription.status}
              </Badge>
            </div>
          ) : (
            <div className="flex items-center justify-between rounded-lg border p-4">
              <div>
                <p className="font-medium">No payment method</p>
                <p className="text-sm text-gray-500">Add a payment method to start your subscription</p>
              </div>
            </div>
          )}
          <Button variant="outline">Update Payment Method</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Billing History</CardTitle>
          <CardDescription>View your past invoices</CardDescription>
        </CardHeader>
        <CardContent>
          {billingHistory?.invoices && billingHistory.invoices.length > 0 ? (
            <div className="space-y-4">
              {billingHistory.invoices.map((invoice) => (
                <div
                  key={invoice.id}
                  className="flex items-center justify-between rounded-lg border p-4"
                >
                  <div>
                    <p className="font-medium">{invoice.id}</p>
                    <p className="text-sm text-gray-500">{invoice.date}</p>
                  </div>
                  <div className="flex items-center gap-4">
                    <p className="font-medium">{formatCurrency(invoice.amount, invoice.currency)}</p>
                    <Badge variant={getStatusVariant(invoice.status)}>{invoice.status}</Badge>
                    <Button variant="outline" size="sm">
                      <Download className="mr-1 h-3 w-3" />
                      PDF
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500">No billing history available</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
