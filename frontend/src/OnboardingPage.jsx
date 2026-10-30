import React, { useState, useEffect } from 'react';
import { Copy, Download, CheckCircle, Terminal, Book, ExternalLink } from 'lucide-react';

const OnboardingPage = () => {
  const [selectedPlatform, setSelectedPlatform] = useState(null);
  const [copied, setCopied] = useState(false);
  const [masterUrl, setMasterUrl] = useState('');

  // Auto-detect user's platform
  useEffect(() => {
    const detectPlatform = () => {
      const userAgent = navigator.userAgent.toLowerCase();
      const platform = navigator.platform.toLowerCase();

      if (platform.includes('win')) return 'windows';
      if (platform.includes('mac')) return 'macos';
      if (platform.includes('linux')) {
        if (userAgent.includes('ubuntu')) return 'ubuntu';
        if (userAgent.includes('debian')) return 'debian';
        if (userAgent.includes('fedora')) return 'fedora';
        if (userAgent.includes('arch')) return 'arch';
        return 'ubuntu';
      }
      if (platform.includes('freebsd')) return 'freebsd';
      return 'ubuntu';
    };

    const detected = detectPlatform();
    setSelectedPlatform(detected);

    const url = `${window.location.protocol}//${window.location.hostname}`;
    setMasterUrl(url);
  }, []);

  const platforms = [
    {
      id: 'ubuntu',
      name: 'Ubuntu / Debian',
      icon: 'server',
      family: 'debian',
      color: 'bg-orange-500',
      packageFormat: '.deb',
      installCmd: (url) => {
        const host = url.replace(/^https?:\/\//, '');
        return `curl -fsSL ${url}:3000/download/install-ubuntu.sh | sudo bash -s -- ${host}`;
      },
      downloadUrl: '/download/agent-latest.deb',
      popular: true
    },
    {
      id: 'rhel',
      name: 'RHEL / Rocky / Alma',
      icon: 'server',
      family: 'rhel',
      color: 'bg-red-600',
      packageFormat: '.rpm',
      installCmd: (url) => {
        const host = url.replace(/^https?:\/\//, '');
        return `curl -fsSL ${url}:3000/download/install-rhel.sh | sudo bash -s -- ${host}`;
      },
      downloadUrl: '/download/agent-latest.rpm',
      popular: true
    },
    {
      id: 'arch',
      name: 'Arch Linux',
      icon: 'server',
      family: 'arch',
      color: 'bg-blue-600',
      packageFormat: '.pkg.tar.zst',
      installCmd: (url) => {
        const host = url.replace(/^https?:\/\//, '');
        return `curl -fsSL ${url}:3000/download/install-arch.sh | sudo bash -s -- ${host}`;
      },
      downloadUrl: '/download/agent-latest.pkg.tar.zst',
      popular: false
    },
    {
      id: 'alpine',
      name: 'Alpine Linux',
      icon: 'server',
      family: 'alpine',
      color: 'bg-blue-400',
      packageFormat: '.apk',
      installCmd: (url) => {
        const host = url.replace(/^https?:\/\//, '');
        return `wget -qO- ${url}:3000/download/install-alpine.sh | sudo sh -s -- ${host}`;
      },
      downloadUrl: '/download/agent-latest.apk',
      popular: false
    },
    {
      id: 'amazon',
      name: 'Amazon Linux',
      icon: 'server',
      family: 'rhel',
      color: 'bg-yellow-600',
      packageFormat: '.rpm',
      installCmd: (url) => {
        const host = url.replace(/^https?:\/\//, '');
        return `curl -fsSL ${url}:3000/download/install-amazon.sh | sudo bash -s -- ${host}`;
      },
      downloadUrl: '/download/agent-latest.rpm',
      popular: true
    },
    {
      id: 'opensuse',
      name: 'openSUSE',
      icon: 'server',
      family: 'suse',
      color: 'bg-green-600',
      packageFormat: '.rpm',
      installCmd: (url) => {
        const host = url.replace(/^https?:\/\//, '');
        return `curl -fsSL ${url}:3000/download/install-opensuse.sh | sudo bash -s -- ${host}`;
      },
      downloadUrl: '/download/agent-opensuse.rpm',
      popular: false
    },
    {
      id: 'freebsd',
      name: 'FreeBSD',
      icon: 'server',
      family: 'bsd',
      color: 'bg-red-700',
      packageFormat: '.txz',
      installCmd: (url) => {
        const host = url.replace(/^https?:\/\//, '');
        return `fetch -qo - ${url}:3000/download/install-freebsd.sh | sudo sh -s -- ${host}`;
      },
      downloadUrl: '/download/agent-latest.txz',
      popular: false
    },
    {
      id: 'windows',
      name: 'Windows',
      icon: 'server',
      family: 'windows',
      color: 'bg-blue-500',
      packageFormat: '.exe',
      installCmd: (url) => `irm ${url}:3000/download/install-windows.ps1 | iex`,
      downloadUrl: '/download/patchmaster-agent-installer.exe',
      popular: true
    }
  ];

  const selected = platforms.find(p => p.id === selectedPlatform);

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-6">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold text-gray-900 mb-4">
            Welcome to Patch-SecOps Solution! 🚀
          </h1>
          <p className="text-xl text-gray-600">
            Choose your operating system to get started
          </p>
          <p className="text-sm text-gray-500 mt-2">
            Universal patch management for all platforms
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {platforms.map((platform) => (
            <button
              key={platform.id}
              onClick={() => setSelectedPlatform(platform.id)}
              className={`relative p-6 rounded-xl border-2 transition-all duration-200 ${
                selectedPlatform === platform.id
                  ? 'border-blue-500 bg-white shadow-lg scale-105'
                  : 'border-gray-200 bg-white hover:border-gray-300 hover:shadow-md'
              }`}
            >
              {platform.popular && (
                <span className="absolute top-2 right-2 bg-green-500 text-white text-xs px-2 py-1 rounded-full">
                  Popular
                </span>
              )}
              <div className="text-5xl mb-3">{platform.icon}</div>
              <div className="text-sm font-semibold text-gray-900">{platform.name}</div>
              <div className="text-xs text-gray-500 mt-1">{platform.packageFormat}</div>
            </button>
          ))}
        </div>

        {selected && (
          <div className="bg-white rounded-xl shadow-lg p-8 mb-8">
            <div className="flex items-center mb-6">
              <div className="text-4xl mr-4">{selected.icon}</div>
              <div>
                <h2 className="text-2xl font-bold text-gray-900">{selected.name}</h2>
                <p className="text-gray-600">Quick installation guide</p>
              </div>
            </div>

            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Patch-SecOps Solution Master URL
              </label>
              <input
                type="text"
                value={masterUrl}
                onChange={(e) => setMasterUrl(e.target.value)}
                placeholder="http://192.168.1.100"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <p className="text-xs text-gray-500 mt-1">
                Enter your Patch-SecOps Solution server URL (auto-detected: {masterUrl})
              </p>
            </div>

            <div className="mb-6">
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium text-gray-700 flex items-center">
                  <Terminal className="w-4 h-4 mr-2" />
                  One-Line Installation
                </label>
                <button
                  onClick={() => copyToClipboard(selected.installCmd(masterUrl))}
                  className="flex items-center text-sm text-blue-600 hover:text-blue-700"
                >
                  {copied ? (
                    <>
                      <CheckCircle className="w-4 h-4 mr-1" />
                      Copied!
                    </>
                  ) : (
                    <>
                      <Copy className="w-4 h-4 mr-1" />
                      Copy
                    </>
                  )}
                </button>
              </div>
              <div className="bg-gray-900 text-green-400 p-4 rounded-lg font-mono text-sm overflow-x-auto">
                {selected.installCmd(masterUrl)}
              </div>
            </div>

            <div className="border-t pt-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                Or download the agent package manually
              </h3>
              <div className="flex flex-wrap gap-4">
                <a
                  href={`${masterUrl}:3000${selected.downloadUrl}`}
                  className="flex items-center px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  <Download className="w-5 h-5 mr-2" />
                  Download {selected.packageFormat}
                </a>
                <a
                  href={`/docs/install/${selected.id.toUpperCase()}.md`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center px-6 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  <Book className="w-5 h-5 mr-2" />
                  Installation Guide
                </a>
              </div>
            </div>

            <div className="mt-8 bg-blue-50 rounded-lg p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                Installation Steps
              </h3>
              <ol className="space-y-3">
                <li className="flex items-start">
                  <span className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm mr-3">
                    1
                  </span>
                  <span className="text-gray-700">
                    Copy the installation command above
                  </span>
                </li>
                <li className="flex items-start">
                  <span className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm mr-3">
                    2
                  </span>
                  <span className="text-gray-700">
                    Run it on your {selected.name} system with sudo/root privileges
                  </span>
                </li>
                <li className="flex items-start">
                  <span className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm mr-3">
                    3
                  </span>
                  <span className="text-gray-700">
                    The agent will automatically register with the master server
                  </span>
                </li>
                <li className="flex items-start">
                  <span className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm mr-3">
                    4
                  </span>
                  <span className="text-gray-700">
                    Your host will appear in the dashboard within 60 seconds
                  </span>
                </li>
              </ol>
            </div>

            <div className="mt-6 bg-green-50 rounded-lg p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
                <CheckCircle className="w-5 h-5 mr-2 text-green-600" />
                Verify Installation
              </h3>
              <div className="space-y-2 text-sm text-gray-700">
                {selected.family === 'windows' ? (
                  <>
                    <p>• Check service status: <code className="bg-gray-100 px-2 py-1 rounded">Get-Service PatchMaster*</code></p>
                    <p>• View logs: <code className="bg-gray-100 px-2 py-1 rounded">Get-Content &quot;C:\Program Files\PatchMaster-Agent\logs\agent.log&quot;</code></p>
                  </>
                ) : (
                  <>
                    <p>• Check service status: <code className="bg-gray-100 px-2 py-1 rounded">systemctl status patch-agent</code></p>
                    <p>• View logs: <code className="bg-gray-100 px-2 py-1 rounded">journalctl -u patch-agent -f</code></p>
                    <p>• Test API: <code className="bg-gray-100 px-2 py-1 rounded">curl http://localhost:8080/health</code></p>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="grid md:grid-cols-3 gap-6 mb-8">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="text-3xl mb-3">🚀</div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Fast Installation</h3>
            <p className="text-gray-600 text-sm">
              One-line command installs and configures the agent in seconds
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <div className="text-3xl mb-3">🔒</div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Secure & Reliable</h3>
            <p className="text-gray-600 text-sm">
              Encrypted communication and automatic reconnection
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <div className="text-3xl mb-3">server</div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Offline Support</h3>
            <p className="text-gray-600 text-sm">
              All dependencies bundled - works in air-gapped environments
            </p>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6 text-center">
          <h3 className="text-lg font-semibold text-gray-900 mb-2">Need Help?</h3>
          <p className="text-gray-600 mb-4">
            Check our comprehensive documentation or contact support
          </p>
          <div className="flex justify-center gap-4">
            <a
              href="/docs"
              className="flex items-center text-blue-600 hover:text-blue-700"
            >
              <Book className="w-4 h-4 mr-1" />
              Documentation
            </a>
            <a
              href="https://github.com/VYGROUP/patchmaster"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center text-blue-600 hover:text-blue-700"
            >
              <ExternalLink className="w-4 h-4 mr-1" />
              GitHub
            </a>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OnboardingPage;
