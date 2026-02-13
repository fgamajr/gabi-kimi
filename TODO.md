# TDD Implementation Plan

## Phase 1: Write Failing Tests (RED)
1. Create Comparison Contracts (src/Gabi.Contracts/Comparison/)
   - LinkComparisonResult record
   - ComparisonAction enum  
   - BatchComparisonResult record
   - DiscoveredLink record (need to create this contract)

2. Write Tests First (tests/Gabi.Discover.Tests/LinkComparatorTests.cs)
   - Compare new link returns Insert
   - Compare unchanged link returns Skip
   - Compare link with changed metadata returns Update
   - Batch compare calculates counts correctly
   - MetadataHash is consistent for same metadata
   - MetadataHash changes when metadata changes

## Phase 2: Implement to Pass Tests (GREEN)
3. Create ILinkComparator interface (src/Gabi.Contracts/Comparison/)
4. Implement LinkComparator (src/Gabi.Discover/LinkComparator.cs)
5. Update IDiscoveredLinkRepository interface
6. Implement repository methods
7. Create IDeduplicationService interface

## Phase 3: Refactor (if needed)
8. Verify build passes
