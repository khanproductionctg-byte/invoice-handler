'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Plus, Search, Mail, Phone } from "lucide-react"
import { api } from '@/lib/api'

interface Customer {
  id: number
  email: string
  phone?: string
  full_name?: string
  company_name?: string
  opt_out_email: boolean
  opt_out_sms: boolean
  preferred_language: string
  created_at: string
}

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    fetchCustomers()
  }, [])

  async function fetchCustomers() {
    try {
      setLoading(true)
      const data = await api.getCustomers({ limit: 100 })
      setCustomers(data.data || [])
    } catch (err) {
      console.error('Failed to fetch customers:', err)
      setError('Failed to load customers')
    } finally {
      setLoading(false)
    }
  }

  const filteredCustomers = customers.filter(customer => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        customer.email?.toLowerCase().includes(query) ||
        customer.full_name?.toLowerCase().includes(query) ||
        customer.company_name?.toLowerCase().includes(query)
      )
    }
    return true
  })

  const getCustomerName = (customer: Customer) => {
    return customer.full_name || customer.company_name || customer.email.split('@')[0]
  }

  const getCustomerInitials = (customer: Customer) => {
    const name = getCustomerName(customer)
    return name.substring(0, 2).toUpperCase()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Customers</h1>
          <p className="text-gray-500">Manage your customer database</p>
        </div>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          Add Customer
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>All Customers</CardTitle>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <Input 
                placeholder="Search customers..." 
                className="pl-9 w-64"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : error ? (
            <p className="text-red-500 text-center py-4">{error}</p>
          ) : filteredCustomers.length === 0 ? (
            <p className="text-gray-500 text-center py-4">No customers found</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Customer</TableHead>
                  <TableHead>Contact</TableHead>
                  <TableHead>Preferences</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredCustomers.map((customer) => (
                  <TableRow key={customer.id}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Avatar>
                          <AvatarFallback>
                            {getCustomerInitials(customer)}
                          </AvatarFallback>
                        </Avatar>
                        <div>
                          <p className="font-medium">{getCustomerName(customer)}</p>
                          <p className="text-sm text-gray-500">CUST-{customer.id}</p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        <p className="flex items-center gap-2 text-sm">
                          <Mail className="h-3 w-3 text-gray-400" />
                          {customer.email}
                        </p>
                        {customer.phone && (
                          <p className="flex items-center gap-2 text-sm text-gray-500">
                            <Phone className="h-3 w-3 text-gray-400" />
                            {customer.phone}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        {customer.opt_out_email && (
                          <Badge variant="destructive" className="text-xs">Email Opt-Out</Badge>
                        )}
                        {customer.opt_out_sms && (
                          <Badge variant="destructive" className="text-xs">SMS Opt-Out</Badge>
                        )}
                        {!customer.opt_out_email && !customer.opt_out_sms && (
                          <p className="text-sm text-gray-500">—</p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="success">
                        Active
                      </Badge>
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
