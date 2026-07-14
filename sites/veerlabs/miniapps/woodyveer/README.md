# WoodVeer - TimberMate

**A comprehensive React Native mobile application for timber measurement, estimation, cost analysis, and cutting optimization.**

![React Native](https://img.shields.io/badge/React%20Native-0.72.6-61dafb?logo=react)
![TypeScript](https://img.shields.io/badge/TypeScript-4.8.4-3178c6?logo=typescript)
![OpenCV](https://img.shields.io/badge/OpenCV-Integration-blue)
![Status](https://img.shields.io/badge/Status-Active%20Development-green)

## 📋 Project Overview

**TimberMate** is a sophisticated cross-platform mobile application designed for timber merchants, sawmill operators, forest engineers, and wood product businesses. It provides real-time measurement, intelligent cutting optimization, and comprehensive cost analysis for timber operations.

### Key Capabilities
- 📸 **Real-time camera-based timber measurement** using OpenCV computer vision
- 📐 **Automated dimension extraction** from photographs
- 💰 **Multi-model cost calculation** (per cubic foot, kg, unit, sq ft, hourly)
- ✂️ **Intelligent cutting optimization** to minimize waste
- 📊 **Estimate management** with detailed tracking and history
- 📈 **Wastage analysis** and material utilization reports
- 📱 **Offline-first architecture** with SQLite persistence
- 🖨️ **Professional report generation** for printing/export

## 🎯 Problem It Solves

Traditional timber estimation involves manual measurements, paper-based calculations, and significant guesswork. TimberMate eliminates these inefficiencies by:

1. **Automating measurement capture** - Use your phone camera instead of measuring tapes
2. **Optimizing material usage** - Reduce waste by up to 30-40% through intelligent cutting algorithms
3. **Streamlining cost calculation** - Instant estimates with multiple pricing models
4. **Centralizing records** - All estimates stored and searchable locally
5. **Generating professional reports** - Ready-to-share documentation

## ✨ Core Features

### 1. Timber Measurement & Scanning
- Real-time camera capture with OpenCV analysis
- Automated dimension extraction (length, width, thickness)
- Support for multiple measurement angles
- Artifact scanning for document-based measurements
- Native module integration (iOS Swift + Android Java)

### 2. Estimate Management System
- Create, edit, and manage multiple estimates
- Define custom timber requirements with specifications
- Track multiple wood types per estimate
- Status tracking (draft, in-progress, finalized, saved)
- Full estimate history with timestamps

### 3. Intelligent Optimization Engine
- Calculates optimal cutting patterns from raw timber
- Minimizes waste and sawdust generation
- Supports cross-grain cutting configurations
- Generates multiple solution options
- Identifies scrap material and unused portions
- Provides utilization efficiency metrics

### 4. Dynamic Pricing & Cost Analysis
- **5 pricing models**:
  - Per Cubic Foot (standard)
  - Per Kilogram (weight-based)
  - Per Unit (fixed rate)
  - Per Square Foot (surface area)
  - Per Hour (labor-based)
- Variable rates by wood type
- Real-time cost aggregation
- Profit margin tracking

### 5. Advanced Visualization
- Zoomable/pinchable tile views
- 3D cut visualization (multiple implementations)
- Professional printable layouts
- Material diagram exports

### 6. Data Management
- Local SQLite database
- Redux state management
- Persistent storage across sessions
- Contact management for suppliers/buyers
- Geolocation integration

### 7. Buyer + Store Marketplace Workflows (New)
- Store owner subscription and registration flow (city/area listing)
- Buyer nearest timber store lookup by area with distance sorting
- One-tap directions to store in Apple Maps
- Visited-store activation to apply store-scoped pricing rules
- Home-owner project estimator to draft estimate line-item generation

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                  React Native 0.72.6                            │
│        (TypeScript for type safety and developer experience)    │
├─────────────────────────────────────────────────────────────────┤
│  UI Layer              Navigation            State Management   │
│  ├─ React Native Paper │ ├─Stack Navigator  │ ├─Redux Store   │
│  ├─ Styled Components  │ ├─Tab Navigator    │ ├─Redux Persist │
│  ├─ React Native SVG   │ └─Drawer Navigator │ └─Local Storage │
│  └─ React Native Icons │                    │                  │
├─────────────────────────────────────────────────────────────────┤
│  Business Logic Layer                                            │
│  ├─ Timber Optimization Algorithm                               │
│  ├─ Cost Calculation Engine                                     │
│  ├─ Estimate Fulfillment Logic                                  │
│  └─ Material Analysis                                           │
├─────────────────────────────────────────────────────────────────┤
│  Data Layer                                                      │
│  ├─ SQLite Database (react-native-sqlite-storage)               │
│  ├─ Camera Integration (react-native-camera)                    │
│  ├─ Image Picker & Processing                                  │
│  └─ Geolocation & Maps                                          │
├─────────────────────────────────────────────────────────────────┤
│  Native Modules (Platform-Specific)                             │
│  ├─ iOS: Swift-based TimberMeasurementTool + OpenCV Framework  │
│  └─ Android: Java-based OpenCV Integration                      │
└─────────────────────────────────────────────────────────────────┘
```

## 📂 Project Structure

```
woodyveer/
└── TimberMate/                          # Main application
    ├── ✨ Core Application
    │   ├── App.tsx                      # Entry point
    │   ├── AppNavigator.tsx             # Main navigation setup
    │   ├── MainAppNavigator.tsx         # Alternative navigation
    │   ├── CustomTheme.js               # Theme configuration
    │   ├── styles.ts                    # Global styling
    │   └── theme.js                     # Legacy theme
    │
    ├── 📱 Screens & Components
    │   ├── CameraScreen.tsx             # Camera UI wrapper
    │   ├── CameraComponent.tsx          # Camera logic & capture
    │   ├── TimberMeasurement.tsx        # Measurement interface
    │   ├── ArtifactScan.tsx             # Document scanning
    │   ├── EstimatesManager.tsx         # Main estimate CRUD
    │   ├── EstimateModal.tsx            # Estimate editing dialog
    │   ├── TimberOptimization.tsx       # Optimization UI
    │   ├── TimberOptimizationFinal.tsx  # Solution display
    │   ├── TimberCutView*.tsx           # Cut visualizations (3 versions)
    │   ├── TimberSampling.tsx           # Data collection
    │   ├── ManageSamples.tsx            # Sample management
    │   ├── PrintableView.tsx            # Report generation
    │   ├── PinchableTile.tsx            # Zoomable component
    │   └── Contacts.tsx                 # Contact management
    │
    ├── 🗄️ Data & Database
    │   ├── database.ts                  # SQLite operations & schema
    │   ├── types/
    │   │   ├── interfaces.ts            # TypeScript data models
    │   │   │   ├── Requirement          # Timber requirement spec
    │   │   │   ├── Slab                 # Raw timber piece
    │   │   │   ├── Estimate             # Complete estimate
    │   │   │   ├── Solution             # Optimization result
    │   │   │   └── RateType enum        # 5 pricing models
    │   │   └── constants.ts             # App constants
    │   └── redux/                       # State management (if present)
    │
    ├── 🎨 Assets & Styling
    │   ├── assets/svg/                  # SVG components
    │   ├── Styles/Screens/              # Screen-specific styles
    │   └── CustomTheme.js               # Color & spacing tokens
    │
    ├── 🔧 Native Modules
    │   ├── NativeModules/OpenCV.js      # OpenCV bridge
    │   └── OpenCV/opencv2.framework/    # iOS OpenCV framework
    │
    ├── 📱 Platform Configuration
    │   ├── ios/
    │   │   ├── Podfile                  # CocoaPods dependencies
    │   │   ├── RNOpenCvLibrary.h/mm     # OpenCV binding
    │   │   ├── TimberMeasurementTool.swift/.m
    │   │   └── TimberMate.xcworkspace/  # Xcode workspace
    │   │
    │   └── android/
    │       ├── build.gradle             # Android build config
    │       ├── gradle.properties
    │       └── app/src/main/
    │           └── jniLibs/             # Native libraries
    │
    ├── ⚙️ Configuration Files
    │   ├── package.json                 # Dependencies & scripts
    │   ├── tsconfig.json                # TypeScript config
    │   ├── babel.config.js              # Babel setup
    │   ├── metro.config.js              # Metro bundler config
    │   ├── jest.config.js               # Testing config
    │   ├── react-native.config.js       # RN linking config
    │   └── Gemfile                      # Ruby dependencies (iOS)
    │
    └── 📚 Documentation
        ├── README.md                    # This file
        └── [Additional docs below]
```

## 🚀 Quick Start

### Prerequisites

```
✓ Node.js 16+ with npm/yarn
✓ React Native environment setup
✓ Android SDK 30+ (for Android development)
✓ Xcode 14+ (for iOS development)
✓ JDK 11+
✓ CocoaPods (for iOS)
```

### Installation

```bash
# Clone repository
git clone https://github.com/veeringman/woodyveer.git
cd woodyveer/TimberMate

# Install JavaScript dependencies
npm install
# or
yarn install

# Install iOS native dependencies
cd ios && pod install && cd ..

# Start development server
npm start
```

### Running the App

```bash
# Android (emulator/device)
npm run android

# iOS (simulator/device)
npm run ios

# iOS release on connected iPhone (offline, no Metro dependency)
npm run ios:release:iphone

# Web (if configured)
npm start -- --web
```

## 🧪 Development & Testing

```bash
# Lint code
npm run lint

# Run tests
npm test

# Format code
npx prettier --write .

# Type check
npx tsc --noEmit

# Build production JS bundle for iOS manually
npm run bundle:ios
```

## 📦 Key Dependencies

### Core Framework
- `react` (18.2.0) - UI library
- `react-native` (0.72.6) - Mobile framework
- `typescript` (4.8.4) - Type safety

### Navigation & UI
- `@react-navigation/*` (6.x) - Navigation routing
- `react-native-paper` (5.11.1) - Material Design components
- `react-native-gesture-handler` - Gesture support
- `react-native-reanimated` - Performance animations
- `styled-components` (6.1.0) - Component styling

### State & Storage
- `redux` (4.2.1) - State management
- `react-redux` (8.1.3) - React-Redux bindings
- `redux-persist` (6.0.0) - Persistent state
- `react-native-sqlite-storage` (6.0.1) - Local database

### Hardware & Vision
- `react-native-camera` (4.2.1) - Camera access
- `react-native-opencv` - Computer vision
- `react-native-geolocation-service` - GPS/location
- `react-native-image-picker` - Photo selection
- `react-native-view-shot` - Screenshot capture

### Utilities
- `react-native-maps` - Mapping
- `react-native-vector-icons` - Icon library
- `react-native-svg` - SVG rendering

## 📋 Data Models

### Key TypeScript Interfaces

```typescript
interface Requirement {
  id: number;
  length: string;
  width: string;
  thickness: string;
  count: string;
  fullfilled: number;
  woodType?: string;
}

interface Slab {
  length: string;
  width: string;
  thickness: string;
  rateApplied: string;
  rateType: RateType;
  cost?: number;
  isUsed?: boolean;
  isScrap?: boolean;
}

interface Estimate {
  id: number;
  name: string;
  description: string;
  cost: number;
  volume: number;
  weight: number;
  slabs: Slab[];
  requirements: Requirement[];
  isFinished: boolean;
  isSaved: boolean;
}

enum RateType {
  PerCubicFoot = 'Per Cubic Foot',
  PerKilogram = 'Per Kilogram',
  PerUnit = 'Per Unit',
  PerSquareFoot = 'Per Square Foot',
  PerHour = 'Per Hour'
}
```

## 🗺️ Navigation Flow

```
Home Screen
├── Timber Estimates → EstimatesManager (CRUD)
│   ├── Create new estimate
│   ├── Edit existing estimate
│   ├── View optimization results
│   └── Generate reports
├── Timber Measurement → Camera Capture
│   └── Process with OpenCV
├── Scan Artifact → Document scanning
│   └── Extract measurements
├── Timber Optimization → Algorithm UI
│   ├── Input material specs
│   ├── Define requirements
│   └── View optimal solutions
├── Contacts → Contact Manager
│   ├── Suppliers
│   ├── Buyers
│   └── Stakeholders
└── Zoomable View → Report Preview
    └── Inspect details (pinch-zoom)
```

## 🔌 Native Modules

### iOS (Swift)
- **TimberMeasurementTool.swift** - Core measurement logic
- **MeasurementViewController.swift** - UI integration
- **OpenCV.framework** - Vision capabilities

### Android (Java)
- OpenCV Java bindings
- JNI bridge for native code
- Camera HAL integration

## 💾 Database

Currently uses **SQLite** with the following schema:

```sql
-- Profiles/Estimates table (expandable)
CREATE TABLE profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

*Note: Full schema documentation in [DOCUMENTATION.md](./DOCUMENTATION.md)*

## 📊 Optimization Algorithm

The timber optimization engine works as follows:

```
Input: Raw timber slab + Requirements list
  ↓
1. Calculate slab volume/weight
2. Match slab against requirements
3. Generate cutting patterns
4. Calculate waste & sawdust
5. Track cross-grain orientation
6. Identify scrap material
7. Calculate efficiency metrics
  ↓
Output: Multiple optimization solutions ranked by efficiency
```

## 🐛 Known Issues & Limitations

| Issue | Impact | Workaround |
|-------|--------|-----------|
| OpenCV native module requires proper configuration | High | See SETUP_GUIDE.md |
| Large estimate databases may slow UI | Medium | Implement pagination |
| No cloud sync (offline-first only) | High | Manual export/import |
| Limited error handling in some flows | Medium | Use logs; file issues |
| Test coverage minimal | Medium | Refer to TESTING.md |
| Memory usage with large images | Medium | Implement image compression |

## 🗺️ Roadmap & Enhancements

See **[ENHANCEMENTS.md](./ENHANCEMENTS.md)** for:
- ✅ Cloud synchronization & backup
- ✅ Advanced ML-based wood classification
- ✅ Multi-language support (i18n)
- ✅ Web dashboard companion app
- ✅ Team collaboration features
- ✅ API integration layer
- ✅ Performance optimization
- ✅ Comprehensive testing

## 🔑 Key Algorithms & Formulas

### Volume Calculation
```
Volume (Cubic Feet) = (Length × Width × Thickness) / 12³
```

### Weight Estimation
```
Weight (kg) = Volume × Wood Type Density
```

### Cost Calculation
```
Cost = Base Rate × Quantity × Adjustment Factor
```

### Wastage Percentage
```
Wastage % = (Wasted Material / Total Material) × 100
```

## 📖 Documentation Structure

- **README.md** (this file) - Project overview and quick start
- **DOCUMENTATION.md** - Detailed feature documentation
- **ENHANCEMENTS.md** - Recommended improvements and roadmap
- **CONTRIBUTING.md** - Development guidelines
- **ARCHITECTURE.md** - Technical deep dive
- **API_REFERENCE.md** - Component and function APIs (recommended)

## 🤝 Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for:
- Code style guidelines
- Git workflow
- Pull request process
- Development environment setup

## 📄 License

MIT License - See LICENSE file

## 👥 Support & Contact

- **Repository**: [GitHub - veeringman/woodyveer](https://github.com/veeringman/woodyveer)
- **Issues**: [Report bugs](https://github.com/veeringman/woodyveer/issues)
- **Projects**: [Timber material optimization](https://github.com/veeringman/woodyveer/projects)

## 📈 Performance Metrics

Target benchmarks:
- App startup: < 3 seconds
- Estimate creation: < 500ms
- Optimization calculation: < 2 seconds
- Camera capture: < 1 second
- Database query: < 100ms

## 🛠️ Troubleshooting

### Common Issues

**Metro bundler won't start**
```bash
npm start -- --reset-cache
```

**Dependencies installation fails**
```bash
rm -rf node_modules ios/Pods yarn.lock package-lock.json
npm install && cd ios && pod install && cd ..
```

**OpenCV module not found**
- See platform-specific setup guides
- Ensure iOS Pods and Android Gradle builds completed

**Camera permission denied**
- Check AndroidManifest.xml and Info.plist
- Request runtime permissions before camera access

## 📞 Version History

| Version | Date | Status | Notes |
|---------|------|--------|-------|
| 0.0.1 | May 2026 | Beta | Initial release |
| 0.1.0 | TBD | Planned | Enhanced optimization |
| 0.2.0 | TBD | Planned | Cloud sync |
| 1.0.0 | TBD | Planned | Production release |

---

**Last Updated**: May 2026  
**Maintained By**: WoodVeer Team  
**Community**: Open for contributions and feedback
