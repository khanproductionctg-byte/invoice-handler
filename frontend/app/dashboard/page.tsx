'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  FileText,
  Users,
  DollarSign,
  Clock,
  TrendingUp,
  AlertCircle,
} from "lucide-react"
import { api } from '@/lib/api'

interface DashboardStats {
  total_invoices: number
  overdue_count: number
  overdue_amount: number
  paid_count: number
  reconciliation_rate: number
  pending_count: number
  pending_amount: number
  this_month_invoices: number
  this_month_revenue: number
}

interface Invoice {
  id: number
  invoice_number: string
  vendor_name: string
  amount_due: number
  status: string
  due_date: string
}

const statusVariant = {
  paid: "success",
  pending: "warning",
  overdue: "destructive",
} as const

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [prevStats, setPrevStats] = useState<DashboardStats | null>(null)
  const [recentInvoices, setRecentInvoices] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function fetchData() {
      try {
        // Fetch dashboard stats
        const statsData = await api.getDashboardStats()
        setStats(statsData)

        // Fetch previous month stats for comparison
        const prevMonth = new Date()
        prevMonth.setMonth(prevMonth.getMonth() - 1)
        const prevYear = prevMonth.getFullYear()
        const prevMonthNum = prevMonth.getMonth() + 1
        
        try {
          const prevStatsData = await api.getDashboardStats(prevYear, prevMonthNum)
          setPrevStats(prevStatsData)
        } catch {
          // Previous month stats not available
        }

        // Fetch recent invoices (last 5)
        const invoicesData = await api.getInvoices({ per_page: 5 })
        setRecentInvoices(invoicesData.data || [])
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err)
        setError('Failed to load dashboard data')
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [])

  function getChange(current: number, previous: number): string {
    if (previous === 0) return "+0%"
    const pct = ((current - previous) / previous * 100).toFixed(0)
    return `${Number(pct) > 0 ? '+' : ''}${pct}%`
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500">Loading...</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-red-500">{error}</p>
        </div>
      </div>
    )
  }

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount)
  }

  const statsCards = stats ? [
    {
      title: "Total Invoices",
      value: stats.total_invoices.toLocaleString(),
      change: prevStats ? getChange(stats.total_invoices, prevStats.total_invoices) : "+0%",
      icon: FileText,
    },
    {
      title: "Total Customers",
      value: "—",
      change: "+0%",
      icon: Users,
    },
    {
      title: "Revenue",
      value: formatCurrency(stats.this_month_revenue),
      change: prevStats ? getChange(stats.this_month_revenue, prevStats.this_month_revenue) : "+0%",
      icon: DollarSign,
    },
    {
      title: "Pending Payments",
      value: stats.pending_count.toString(),
      change: prevStats ? getChange(stats.pending_count, prevStats.pending_count) : "+0%",
      icon: Clock,
    },
  ] : []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500">Welcome back! Here&apos;s your business overview.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {statsCards.map((stat) => (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
              <stat.icon className="h-4 w-4 text-gray-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-xs text-gray-500 flex items-center gap-1">
                <TrendingUp className="h-3 w-3 text-green-500" />
                {stat.change} from last month
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
        <Card className="col-span-4">
          <CardHeader>
            <CardTitle>Recent Invoices</CardTitle>
          </CardHeader>
          <CardContent>
            {recentInvoices.length === 0 ? (
              <p className="text-gray-500 text-center py-4">No invoices yet</p>
            ) : (
              <div className="space-y-4">
                {recentInvoices.map((invoice) => (
                  <div
                    key={invoice.id}
                    className="flex items-center justify-between rounded-lg border p-3"
                  >
                    <div className="flex items-center gap-3">
                      <FileText className="h-5 w-5 text-gray-400" />
                      <div>
                        <p className="font-medium">{invoice.invoice_number}</p>
                        <p className="text-sm text-gray-500">{invoice.vendor_name}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="font-medium">{formatCurrency(invoice.amount_due)}</p>
                      <Badge variant={statusVariant[invoice.status as keyof typeof statusVariant] || 'warning'}>
                        {invoice.status}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="col-span-3">
          <CardHeader>
            <CardTitle>Alerts</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {stats && stats.overdue_count > 0 && (
                <div className="flex items-start gap-3 rounded-lg border p-3">
                  <AlertCircle className="h-5 w-5 text-yellow-500" />
                  <div>
                    <p className="font-medium">{stats.overdue_count} invoices overdue</p>
                    <p className="text-sm text-gray-500">
                      {formatCurrency(stats.overdue_amount)} total
                    </p>
                  </div>
                </div>
              )}
              {stats && stats.pending_count > 0 && (
                <div className="flex items-start gap-3 rounded-lg border p-3">
                  <Clock className="h-5 w-5 text-blue-500" />
                  <div>
                    <p className="font-medium">{stats.pending_count} payments pending</p>
                    <p className="text-sm text-gray-500">
                      {formatCurrency(stats.pending_amount)} total
                    </p>
                  </div>
                </div>
              )}
              {(!stats || (stats.overdue_count === 0 && stats.pending_count === 0)) && (
                <p className="text-gray-500 text-center py-4">No alerts</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
