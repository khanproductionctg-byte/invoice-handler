'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Bell, Search, Send, Clock, CheckCircle, Loader2 } from "lucide-react"
import { api } from '@/lib/api'

interface Reminder {
  id: number
  invoice_id: number
  invoice_number: string
  customer_name: string
  amount_due: number
  currency: string
  due_date: string
  status: 'pending' | 'sent' | 'failed'
  reminder_type: string | null
  scheduled_for: string | null
  sent_at: string | null
}

interface ReminderStats {
  pending: number
  sent_today: number
  failed: number
}

const typeLabels: Record<string, string> = {
  first: "First Reminder",
  second: "Second Reminder",
  final: "Final Notice",
  escalation: "Escalation",
  overdue: "Overdue Notice",
  payment_due: "Payment Due",
  reminder: "Friendly Reminder",
}

const typeVariant: Record<string, "default" | "destructive" | "warning" | "secondary"> = {
  first: "secondary",
  second: "warning",
  final: "destructive",
  escalation: "destructive",
  overdue: "destructive",
  payment_due: "warning",
  reminder: "secondary",
}

const statusVariant: Record<string, "warning" | "success" | "destructive"> = {
  pending: "warning",
  sent: "success",
  failed: "destructive",
}

export default function RemindersPage() {
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [stats, setStats] = useState<ReminderStats>({ pending: 0, sent_today: 0, failed: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [searchQuery, setSearchQuery] = useState("")

  useEffect(() => {
    fetchReminders()
    fetchStats()
  }, [])

  const fetchReminders = async () => {
    try {
      setLoading(true)
      const data = await api.get<Reminder[]>('/api/v1/reminders')
      setReminders(data)
    } catch (err) {
      setError('Failed to load reminders')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const data = await api.get<ReminderStats>('/api/v1/reminders/stats')
      setStats(data)
    } catch (err) {
      console.error('Failed to load stats:', err)
    }
  }

  const filteredReminders = reminders.filter(r => {
    if (statusFilter !== "all" && r.status !== statusFilter) return false
    if (searchQuery && !r.invoice_number.toLowerCase().includes(searchQuery.toLowerCase()) &&
        !r.customer_name.toLowerCase().includes(searchQuery.toLowerCase())) {
      return false
    }
    return true
  })

  const formatAmount = (amount: number, currency: string) => {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency || 'USD' }).format(amount)
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-'
    try {
      return new Date(dateStr).toLocaleDateString()
    } catch {
      return dateStr
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
          <h1 className="text-3xl font-bold text-gray-900">Reminders</h1>
          <p className="text-gray-500">Manage automated payment reminders</p>
        </div>
        <Button>
          <Bell className="mr-2 h-4 w-4" />
          Create Reminder
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Pending</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.pending}</div>
            <p className="text-xs text-gray-500">Reminders waiting to be sent</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Sent Today</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.sent_today}</div>
            <p className="text-xs text-gray-500">Reminders sent successfully</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Failed</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.failed}</div>
            <p className="text-xs text-gray-500">Reminders that failed to send</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>All Reminders</CardTitle>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <Input 
                  placeholder="Search reminders..." 
                  className="pl-9 w-64" 
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
              <Select defaultValue="all" value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-32">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="sent">Sent</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {filteredReminders.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              No reminders found
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Invoice</TableHead>
                  <TableHead>Customer</TableHead>
                  <TableHead>Amount</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Due Date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredReminders.map((reminder) => (
                  <TableRow key={reminder.id}>
                    <TableCell className="font-medium">{reminder.invoice_number}</TableCell>
                    <TableCell>{reminder.customer_name}</TableCell>
                    <TableCell>{formatAmount(reminder.amount_due, reminder.currency)}</TableCell>
                    <TableCell>
                      <Badge variant={typeVariant[reminder.reminder_type || 'reminder'] || "secondary"}>
                        {typeLabels[reminder.reminder_type || 'reminder'] || reminder.reminder_type || 'Reminder'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Clock className="h-3 w-3 text-gray-400" />
                        {formatDate(reminder.sent_at || reminder.scheduled_for)}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant[reminder.status]}>
                        {reminder.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {reminder.status === "pending" && (
                        <Button size="sm" variant="outline">
                          <Send className="mr-1 h-3 w-3" />
                          Send Now
                        </Button>
                      )}
                      {reminder.status === "sent" && (
                        <span className="flex items-center gap-1 text-sm text-gray-500">
                          <CheckCircle className="h-3 w-3 text-green-500" />
                          Sent
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
