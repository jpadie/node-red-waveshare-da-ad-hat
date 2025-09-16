#!/bin/bash
# Deployment script with proper timeouts

set -e  # Exit on any error

PI_HOST="10.10.10.157"
PI_USER="jpadie"
TIMEOUT="30"  # 30 second timeout for all operations

echo "🚀 Starting deployment with timeout controls..."

# Function for SSH with timeout
ssh_timeout() {
    timeout $TIMEOUT ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 $PI_USER@$PI_HOST "$1"
}

# Function for SCP with timeout  
scp_timeout() {
    timeout $TIMEOUT scp -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$1" $PI_USER@$PI_HOST:"$2"
}

echo "📦 Creating deployment package..."
npm pack

PACKAGE_FILE=$(ls jpadie-waveshare-da-ad-hat-*.tgz | head -1)
echo "📦 Package created: $PACKAGE_FILE"

echo "🔄 Stopping Node-RED safely..."
ssh_timeout "sudo systemctl stop nodered || echo 'Node-RED was not running'"

echo "📁 Deploying files directly to node_modules..."
# Deploy key files directly
scp_timeout "python/waveSharePythonWorker.py" "~/.node-red/node_modules/@jpadie/waveshare-da-ad-hat/python/"
scp_timeout "python/waveSharePython.py" "~/.node-red/node_modules/@jpadie/waveshare-da-ad-hat/python/"
scp_timeout "nodes/waveshare-ad.js" "~/.node-red/node_modules/@jpadie/waveshare-da-ad-hat/nodes/"
scp_timeout "nodes/waveshare-da.js" "~/.node-red/node_modules/@jpadie/waveshare-da-ad-hat/nodes/"
scp_timeout "nodes/waveshare-ad-multi.js" "~/.node-red/node_modules/@jpadie/waveshare-da-ad-hat/nodes/"
scp_timeout "nodes/waveshare-ad-multi.html" "~/.node-red/node_modules/@jpadie/waveshare-da-ad-hat/nodes/"
scp_timeout "package.json" "~/.node-red/node_modules/@jpadie/waveshare-da-ad-hat/"

echo "🧹 Cleaning up old files..."
ssh_timeout "cd ~/.node-red/node_modules/@jpadie/waveshare-da-ad-hat/nodes && rm -f waveshare-ad-config.js waveshare-ad-stream.* || echo 'Files already clean'"

echo "🔄 Starting Node-RED..."
ssh_timeout "sudo systemctl start nodered"

echo "⏱️  Waiting for Node-RED to start..."
sleep 8

echo "✅ Testing Node-RED response..."
if ssh_timeout "curl -s --connect-timeout 5 http://localhost:1880/ | head -1 | grep -q DOCTYPE"; then
    echo "✅ Node-RED is responding!"
else
    echo "❌ Node-RED may not be responding properly"
fi

echo "📊 Checking Node-RED logs for errors..."
ssh_timeout "sudo journalctl -u nodered --no-pager -n 10 | grep -E '(ERROR|error|Error)' || echo 'No recent errors found'"

echo "🎉 Deployment complete!"

# Cleanup local package
rm -f $PACKAGE_FILE

echo "🧪 Ready for testing:"
echo "   • Single ADC: waveshare-ad node"  
echo "   • Multi ADC: waveshare-ad-multi node"
echo "   • DAC: waveshare-da node"
echo "   • Node-RED UI: http://$PI_HOST:1880"


