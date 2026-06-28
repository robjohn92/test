-- Sample schema to prove the end-to-end path: Azure SQL -> Power BI.
-- Run this once after the database is deployed (see azure/README.md).
-- Replace / extend with your own tables once the sample is working.

IF OBJECT_ID('dbo.sales', 'U') IS NOT NULL
    DROP TABLE dbo.sales;
GO

CREATE TABLE dbo.sales (
    sale_id      INT            IDENTITY(1,1) PRIMARY KEY,
    sale_date    DATE           NOT NULL,
    region       NVARCHAR(50)   NOT NULL,
    product      NVARCHAR(100)  NOT NULL,
    quantity     INT            NOT NULL,
    unit_price   DECIMAL(10, 2) NOT NULL,
    amount       AS (quantity * unit_price) PERSISTED  -- computed column
);
GO

-- A few rows so Power BI has something to chart immediately.
INSERT INTO dbo.sales (sale_date, region, product, quantity, unit_price) VALUES
    ('2026-01-05', 'North', 'Widget A', 10, 9.99),
    ('2026-01-07', 'South', 'Widget B',  4, 24.50),
    ('2026-02-02', 'North', 'Widget A',  7, 9.99),
    ('2026-02-15', 'East',  'Widget C', 20, 4.75),
    ('2026-03-01', 'West',  'Widget B',  2, 24.50),
    ('2026-03-22', 'South', 'Widget C', 15, 4.75);
GO
