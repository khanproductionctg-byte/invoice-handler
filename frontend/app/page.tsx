import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      {/* Header */}
      <header className="border-b bg-white/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold">IH</span>
            </div>
            <span className="text-xl font-bold text-gray-900">Invoice Handler</span>
          </div>
          <nav className="hidden md:flex items-center space-x-4">
            <Link href="/sign-in" className="text-gray-600 hover:text-gray-900">
              Sign In
            </Link>
            <Link href="/sign-up">
              <Button>Get Started</Button>
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="py-20 md:py-32">
        <div className="container mx-auto px-4 text-center">
          <h1 className="text-4xl md:text-6xl font-bold text-gray-900 mb-6">
            Automate Invoice Reconciliation
            <span className="text-blue-600"> with AI</span>
          </h1>
          <p className="text-xl text-gray-600 mb-8 max-w-2xl mx-auto">
            Connect your Gmail, QuickBooks, Xero, and bank accounts. 
            Let AI match payments, send reminders, and generate reports automatically.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link href="/sign-up">
              <Button size="lg" className="text-lg px-8">
                Start Free Trial
              </Button>
            </Link>
            <Link href="#features">
              <Button size="lg" variant="outline" className="text-lg px-8">
                See Features
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-20 bg-white">
        <div className="container mx-auto px-4">
          <h2 className="text-3xl font-bold text-center mb-12">
            Everything You Need for Automated Reconciliation
          </h2>
          <div className="grid md:grid-cols-3 gap-8">
            <div className="p-6 rounded-xl border bg-card">
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mb-4">
                <span className="text-2xl">📧</span>
              </div>
              <h3 className="text-xl font-semibold mb-2">Smart Ingestion</h3>
              <p className="text-gray-600">
                Connect Gmail, Google Drive, QuickBooks, Xero, and Plaid to automatically import invoices.
              </p>
            </div>
            <div className="p-6 rounded-xl border bg-card">
              <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center mb-4">
                <span className="text-2xl">🔍</span>
              </div>
              <h3 className="text-xl font-semibold mb-2">AI Reconciliation</h3>
              <p className="text-gray-600">
                Machine learning matches payments to invoices with confidence scoring and anomaly detection.
              </p>
            </div>
            <div className="p-6 rounded-xl border bg-card">
              <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center mb-4">
                <span className="text-2xl">📨</span>
              </div>
              <h3 className="text-xl font-semibold mb-2">Automated Chasing</h3>
              <p className="text-gray-600">
                Personalized email and SMS reminders with escalation from gentle to firm.
              </p>
            </div>
            <div className="p-6 rounded-xl border bg-card">
              <div className="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center mb-4">
                <span className="text-2xl">📊</span>
              </div>
              <h3 className="text-xl font-semibold mb-2">Reports & Forecasting</h3>
              <p className="text-gray-600">
                Weekly/monthly reports with cash flow forecasting and tax-ready exports.
              </p>
            </div>
            <div className="p-6 rounded-xl border bg-card">
              <div className="w-12 h-12 bg-red-100 rounded-lg flex items-center justify-center mb-4">
                <span className="text-2xl">🔒</span>
              </div>
              <h3 className="text-xl font-semibold mb-2">Secure & Compliant</h3>
              <p className="text-gray-600">
                Enterprise-grade security with audit logs and SOC2 compliance ready.
              </p>
            </div>
            <div className="p-6 rounded-xl border bg-card">
              <div className="w-12 h-12 bg-indigo-100 rounded-lg flex items-center justify-center mb-4">
                <span className="text-2xl">⚡</span>
              </div>
              <h3 className="text-xl font-semibold mb-2">API Access</h3>
              <p className="text-gray-600">
                Full REST API for custom integrations and workflow automation.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="py-20 bg-gray-50">
        <div className="container mx-auto px-4">
          <h2 className="text-3xl font-bold text-center mb-4">Simple, Transparent Pricing</h2>
          <p className="text-gray-600 text-center mb-12">Start free, upgrade when you need more</p>
          <div className="grid md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            {/* Free */}
            <div className="p-6 rounded-xl border bg-white">
              <h3 className="text-xl font-semibold mb-2">Free</h3>
              <p className="text-4xl font-bold mb-4">$0<span className="text-lg font-normal text-gray-500">/mo</span></p>
              <ul className="space-y-2 text-gray-600 mb-6">
                <li>✓ 25 invoices/month</li>
                <li>✓ 10 emails/month</li>
                <li>✓ Gmail integration</li>
                <li>✓ Basic reports</li>
              </ul>
              <Link href="/sign-up" className="block">
                <Button variant="outline" className="w-full">Get Started</Button>
              </Link>
            </div>
            {/* Pro */}
            <div className="p-6 rounded-xl border-2 border-blue-600 bg-white relative">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-blue-600 text-white px-3 py-1 rounded-full text-sm">Popular</div>
              <h3 className="text-xl font-semibold mb-2">Pro</h3>
              <p className="text-4xl font-bold mb-4">$29<span className="text-lg font-normal text-gray-500">/mo</span></p>
              <ul className="space-y-2 text-gray-600 mb-6">
                <li>✓ 500 invoices/month</li>
                <li>✓ 200 emails + 50 SMS</li>
                <li>✓ All integrations</li>
                <li>✓ API access</li>
                <li>✓ Priority support</li>
              </ul>
              <Link href="/sign-up" className="block">
                <Button className="w-full">Start Free Trial</Button>
              </Link>
            </div>
            {/* Enterprise */}
            <div className="p-6 rounded-xl border bg-white">
              <h3 className="text-xl font-semibold mb-2">Enterprise</h3>
              <p className="text-4xl font-bold mb-4">$99<span className="text-lg font-normal text-gray-500">/mo</span></p>
              <ul className="space-y-2 text-gray-600 mb-6">
                <li>✓ Unlimited invoices</li>
                <li>✓ Unlimited emails & SMS</li>
                <li>✓ Custom integrations</li>
                <li>✓ Dedicated support</li>
                <li>✓ Custom reporting</li>
              </ul>
              <Link href="/contact" className="block">
                <Button variant="outline" className="w-full">Contact Sales</Button>
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 bg-gray-900 text-white">
        <div className="container mx-auto px-4">
          <div className="flex flex-col md:flex-row justify-between items-center">
            <div className="flex items-center space-x-2 mb-4 md:mb-0">
              <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold">IH</span>
              </div>
              <span className="text-xl font-bold">Invoice Handler</span>
            </div>
            <div className="flex space-x-6 text-gray-400">
              <Link href="/privacy" className="hover:text-white">Privacy</Link>
              <Link href="/terms" className="hover:text-white">Terms</Link>
              <Link href="/support" className="hover:text-white">Support</Link>
            </div>
          </div>
          <p className="text-center text-gray-500 mt-8">
            © 2026 Invoice Handler. All rights reserved.
          </p>
        </div>
      </footer>
    </div>
  );
}
